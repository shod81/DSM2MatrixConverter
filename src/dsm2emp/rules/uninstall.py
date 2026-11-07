"""Uninstall synthesis and command inversion for DSM-to-Empirum migration."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from dsm2emp.ast.nodes import (
    CallStmt,
    Command,
    Comparison,
    IfStmt,
    RegEntry,
    SectionLine,
)
from dsm2emp.ast.values import LiteralValue, Value, VarRef
from dsm2emp.parser.escript.lexer import unquote
from dsm2emp.parser.ir import IrCommand, IrIf, IrLiteral, IrNode, IrTodo
from dsm2emp.parser.nir import REG_ROOT_MAP
from dsm2emp.rules.model import RuleTrace
from dsm2emp.rules.msi import resolve_msi_guid

# Canonical unquote alias for backward compatibility
_unquote = unquote


def normalize_payload_subpath(path_str: str) -> str:
    """Normalize relative payload subpaths (Extern$, Files, .\\) to %SRC%\\Files layout."""
    s = path_str.strip().strip("'\"")
    norm = s.replace("/", "\\")
    if norm.lower().startswith("%src%\\files\\"):
        return norm
    if norm.lower().startswith("%src%\\"):
        return norm
    for prefix in (
        ".\\Extern$\\",
        ".\\Files\\",
        "Extern$\\",
        "Files\\",
        ".\\",
    ):
        if norm.lower().startswith(prefix.lower()):
            norm = norm[len(prefix) :]
            break
    norm = norm.lstrip("\\/")
    return f"%SRC%\\Files\\{norm}"


_normalize_payload_subpath = normalize_payload_subpath


class UninstallSynthesizer:
    """Synthesizes an inverted uninstall section (Set:Deinstallation) from install commands."""

    def __init__(
        self,
        translate_str_func: Callable[[Any], str],
        quote_func: Callable[[str], str],
        collected_reg_entries: list[RegEntry],
        package_root: Path | None = None,
        media_files: Sequence[Path] | None = None,
        msi_product_codes: Mapping[str, str] | None = None,
    ) -> None:
        self.translate_value_to_str = translate_str_func
        self._quote_path_if_needed = quote_func
        self._collected_reg_entries = collected_reg_entries
        self.package_root = package_root
        self.media_files = media_files
        self.msi_product_codes = msi_product_codes

    def extract_install_commands(self, nodes: list[IrNode]) -> list[IrCommand]:
        """Recursively extract install IrCommands from IR nodes, skipping uninstall blocks."""
        cmds: list[IrCommand] = []
        for node in nodes:
            if isinstance(node, IrCommand):
                cmds.append(node)
            elif isinstance(node, IrIf):
                if node.conditions and len(node.conditions) == 1:
                    c = node.conditions[0]
                    if (c.func_name or "").lower() == "checkinstallmode" and c.func_args:
                        arg_str = (
                            self.translate_value_to_str(c.func_args[0]).lower().strip("\"'")
                        )
                        if arg_str == "imuninstall" and not c.negated:
                            continue
                        if arg_str == "imuserpart" and not c.negated:
                            continue
                cmds.extend(self.extract_install_commands(node.then_body))
                cmds.extend(self.extract_install_commands(node.else_body))
        return cmds

    def synthesize(
        self,
        install_nodes: list[IrNode],
        traces: list[RuleTrace],
        todos: list[IrTodo],
    ) -> list[SectionLine]:
        """Synthesize an inverted Set:Deinstallation section from install nodes."""
        install_cmds = self.extract_install_commands(install_nodes)
        if not install_cmds:
            return []

        proc_lines: list[SectionLine] = []
        uninst_lines: list[SectionLine] = []
        file_lines: list[SectionLine] = []
        dir_lines: list[SectionLine] = []

        for cmd in install_cmds:
            phase, lines = self.invert_single_command(cmd, traces, todos)
            if phase == "proc":
                proc_lines.extend(lines)
            elif phase == "uninst":
                uninst_lines.extend(lines)
            elif phase == "file":
                file_lines.extend(lines)
            elif phase == "dir":
                dir_lines.extend(lines)

        result: list[SectionLine] = []
        result.extend(dir_lines)
        result.extend(file_lines)
        # VAL-011 / Anti-Pattern 6: Windows needs 2-3s after msiexec / uninstaller exits
        # to release file locks. In Empirum reverse mode (/U), -Sleep 3000 executes
        # after uninst_lines and before file/directory deletions.
        if (dir_lines or file_lines) and uninst_lines:
            result.append(
                Command(
                    name="Sleep",
                    args=[LiteralValue(text="3000")],
                    uninstall_only=True,
                )
            )
        result.extend(uninst_lines)
        result.extend(proc_lines)
        return result

    def invert_single_command(
        self,
        cmd: IrCommand,
        traces: list[RuleTrace],
        todos: list[IrTodo],
    ) -> tuple[str, list[SectionLine]]:
        """Invert a single install command into its uninstall counterpart."""
        kind = cmd.kind.lower()

        # 1. KillProcess
        if kind == "killprocess":
            proc_val = cmd.params.get("process_name") or (
                cmd.raw_args[0] if cmd.raw_args else None
            )
            proc_str = self.translate_value_to_str(proc_val) if proc_val else ""
            clean_proc = proc_str.strip("'\"")
            if clean_proc:
                traces.append(
                    RuleTrace(
                        rule_id="M-17",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary=f"KillProcess {clean_proc} for uninstall",
                        doc_ref="KillProcess",
                    )
                )
                return "proc", [
                    Command(
                        name="KillProcess",
                        args=[LiteralValue(text=clean_proc)],
                        uninstall_only=True,
                    )
                ]
            return "", []

        # 2. ExecuteEx / Execute
        if kind in ("executeex", "execute"):
            cmd_val = cmd.params.get("command")
            cmd_str = self.translate_value_to_str(cmd_val) if cmd_val else ""
            cmd_lower = cmd_str.lower()

            # 2a. MSI execution
            if "msiexec" in cmd_lower:
                try:
                    tokens = shlex.split(cmd_str, posix=False)
                except Exception:
                    tokens = cmd_str.split()

                msi_target: str | None = None
                has_quiet = False
                has_norestart = False

                for tok in tokens[1:]:
                    tok_lower = tok.lower()
                    if tok_lower in ("/qn", "/qb", "/quiet", "/passive"):
                        has_quiet = True
                    elif tok_lower in ("/norestart", "/forcerestart"):
                        has_norestart = True
                    elif tok_lower.startswith("reboot="):
                        has_norestart = True
                    elif tok_lower.startswith("/") or tok_lower.startswith("-"):
                        continue
                    elif "=" in tok and not tok.startswith("{"):
                        continue
                    else:
                        if msi_target is None:
                            msi_target = tok

                if msi_target is None:
                    m_msi = re.search(r'("[^"]+\.msi"|\S+\.msi|\{[0-9a-fA-F\-]+\})', cmd_str)
                    if m_msi:
                        msi_target = m_msi.group(1)

                if msi_target:
                    guid = resolve_msi_guid(
                        msi_target,
                        package_root=self.package_root,
                        media_files=self.media_files,
                        msi_product_codes=self.msi_product_codes,
                    )
                    uninst_target = guid if guid else msi_target
                    uninst_args = ["/x", uninst_target]
                    if has_quiet:
                        uninst_args.append("/qn")
                    else:
                        uninst_args.append("/qn")
                    if has_norestart:
                        uninst_args.append("/norestart")

                    msi_lines: list[SectionLine] = [
                        IfStmt(
                            condition=Comparison(
                                left=VarRef(name="ErrorLevel"),
                                relation="!=",
                                right=LiteralValue(text="0"),
                            ),
                            then_target="AbortMSIInst",
                            uninstall_only=True,
                        ),
                        IfStmt(
                            condition=Comparison(
                                left=VarRef(name="ErrorLevel"),
                                relation="==",
                                right=LiteralValue(text="3010"),
                            ),
                            then_target="RebootRequired",
                            uninstall_only=True,
                        ),
                        CallStmt(
                            name="CallHidden",
                            program="msiexec.exe",
                            arguments=[LiteralValue(text=a) for a in uninst_args],
                            uninstall_only=True,
                        ),
                    ]
                    traces.append(
                        RuleTrace(
                            rule_id="M-04",
                            source_line=cmd.src.line,
                            source_raw=cmd.src.raw,
                            confidence="high",
                            target_summary=f"Synthesized MSI Uninstall: msiexec /x {uninst_target}",
                            doc_ref="Call / MsiExec /x",
                        )
                    )
                    return "uninst", msi_lines

            # 2b. Inno Setup installer (/VERYSILENT or /SILENT)
            if "/verysilent" in cmd_lower or "/silent" in cmd_lower:
                inno_lines: list[SectionLine] = [
                    IfStmt(
                        condition=Comparison(
                            left=VarRef(name="ErrorLevel"),
                            relation="!=",
                            right=LiteralValue(text="0"),
                        ),
                        # Not an MSI operation: jump to the standard
                        # deinstallation error section instead of AbortMSIInst,
                        # so non-MSI packages do not need the MSI error section.
                        then_target="Set:DeInstallationError",
                        uninstall_only=True,
                    ),
                    IfStmt(
                        condition=Comparison(
                            left=VarRef(name="ErrorLevel"),
                            relation="==",
                            right=LiteralValue(text="3010"),
                        ),
                        then_target="RebootRequired",
                        uninstall_only=True,
                    ),
                    CallStmt(
                        name="CallHidden",
                        program='"%App%\\unins000.exe"',
                        arguments=[
                            LiteralValue(text="/VERYSILENT"),
                            LiteralValue(text="/NORESTART"),
                        ],
                        uninstall_only=True,
                    ),
                ]
                traces.append(
                    RuleTrace(
                        rule_id="M-01",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary="Synthesized Inno Setup Uninstall: unins000.exe /VERYSILENT",
                        doc_ref="CallHidden unins000.exe",
                    )
                )
                return "uninst", inno_lines

            # 2c. NSIS installer (/S)
            if re.search(r"(?i)(^|\s)[/-]s(\s|$)", cmd_str):
                nsis_lines: list[SectionLine] = [
                    CallStmt(
                        name="CallHidden",
                        program='"%App%\\uninstall.exe"',
                        arguments=[
                            LiteralValue(text="/S"),
                        ],
                        uninstall_only=True,
                    ),
                ]
                traces.append(
                    RuleTrace(
                        rule_id="M-01",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary="Synthesized NSIS Uninstall: uninstall.exe /S",
                        doc_ref="CallHidden uninstall.exe",
                    )
                )
                return "uninst", nsis_lines

            # 2d. Registry command via reg.exe add -> synthesize reg.exe delete
            if "reg.exe" in cmd_lower and " add " in cmd_lower:
                del_cmd = re.sub(
                    r"\breg(?:\.exe)?\s+add\b", "reg.exe delete", cmd_str, flags=re.IGNORECASE
                )
                del_cmd = re.sub(r"\s+/d\s+\S+", "", del_cmd, flags=re.IGNORECASE)
                del_cmd = re.sub(r"\s+/t\s+\S+", "", del_cmd, flags=re.IGNORECASE)
                if "/f" not in del_cmd.lower():
                    del_cmd += " /f"

                parts = del_cmd.split(maxsplit=1)
                prog = parts[0]
                args_list: list[Value | str] = (
                    [LiteralValue(text=a) for a in parts[1].split()] if len(parts) > 1 else []
                )
                reg_lines: list[SectionLine] = [
                    CallStmt(
                        name="CallHidden",
                        program=prog,
                        arguments=args_list,
                        uninstall_only=True,
                    )
                ]
                return "uninst", reg_lines

            return "", []

        # 3. MSIInstallProduct
        if kind == "msiinstallproduct":
            msi_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            msi_str = _unquote(self.translate_value_to_str(msi_val))
            if (
                msi_str
                and not msi_str.startswith("%")
                and not re.match(r"^[a-zA-Z]:", msi_str)
                and not msi_str.startswith("\\\\")
            ):
                msi_str = _normalize_payload_subpath(msi_str)

            guid = resolve_msi_guid(
                msi_str,
                package_root=self.package_root,
                media_files=self.media_files,
                msi_product_codes=self.msi_product_codes,
            )
            target = guid if guid else f'"{msi_str}"'

            msi_inst_lines: list[SectionLine] = [
                IfStmt(
                    condition=Comparison(
                        left=VarRef(name="ErrorLevel"),
                        relation="!=",
                        right=LiteralValue(text="0"),
                    ),
                    then_target="AbortMSIInst",
                    uninstall_only=True,
                ),
                IfStmt(
                    condition=Comparison(
                        left=VarRef(name="ErrorLevel"),
                        relation="==",
                        right=LiteralValue(text="3010"),
                    ),
                    then_target="RebootRequired",
                    uninstall_only=True,
                ),
                CallStmt(
                    name="CallHidden",
                    program="MsiExec.exe",
                    arguments=[
                        LiteralValue(text=f"/X{target}"),
                        LiteralValue(text="/qn"),
                        LiteralValue(text="/norestart"),
                    ],
                    uninstall_only=True,
                ),
            ]
            traces.append(
                RuleTrace(
                    rule_id="M-04",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Synthesized MSI Uninstall for {target}",
                    doc_ref="Call / MsiExec /X",
                )
            )
            return "uninst", msi_inst_lines

        # 4. Copy / InstallFile
        if kind in ("copy", "installfile"):
            dst_val = cmd.params.get("destination") or (
                cmd.raw_args[1] if len(cmd.raw_args) > 1 else None
            )
            dst_str = _unquote(self.translate_value_to_str(dst_val)) if dst_val else ""
            if dst_str:
                is_dir = dst_str.endswith(("\\", "/")) or not re.search(
                    r"\.[a-zA-Z0-9]{1,5}$", dst_str
                )
                if is_dir:
                    traces.append(
                        RuleTrace(
                            rule_id="M-08",
                            source_line=cmd.src.line,
                            source_raw=cmd.src.raw,
                            confidence="high",
                            target_summary=f"Synthesized directory removal: DelTree {dst_str}",
                            doc_ref="RD / DelTree",
                        )
                    )
                    dir_lines: list[SectionLine] = [
                        Command(
                            name="DelTree",
                            args=[
                                LiteralValue(
                                    text=self._quote_path_if_needed(dst_str.rstrip("\\/"))
                                )
                            ],
                            uninstall_only=True,
                        )
                    ]
                    return "dir", dir_lines
                else:
                    traces.append(
                        RuleTrace(
                            rule_id="M-07",
                            source_line=cmd.src.line,
                            source_raw=cmd.src.raw,
                            confidence="high",
                            target_summary=f"Synthesized file cleanup: Del {dst_str}",
                            doc_ref="Del",
                        )
                    )
                    file_lines: list[SectionLine] = [
                        Command(
                            name="Del",
                            args=[LiteralValue(text=self._quote_path_if_needed(dst_str))],
                            uninstall_only=True,
                        )
                    ]
                    return "file", file_lines
            return "", []

        # 5. InstallFileList / CopyFileList
        if kind in ("installfilelist", "copyfilelist"):
            dest_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            dest_str = _unquote(self.translate_value_to_str(dest_val)).rstrip("\\")
            files = cmd.raw_args[1:]
            file_list_lines: list[SectionLine] = []
            if files:
                for f in files:
                    file_str = _unquote(self.translate_value_to_str(f))
                    file_name = file_str.replace("/", "\\").split("\\")[-1]
                    target = f"{dest_str}\\{file_name}" if dest_str else file_name
                    file_list_lines.append(
                        Command(
                            name="Del",
                            args=[LiteralValue(text=self._quote_path_if_needed(target))],
                            uninstall_only=True,
                        )
                    )
            else:
                target = f"{dest_str}\\*.*" if dest_str else "*.*"
                file_list_lines.append(
                    Command(
                        name="Del",
                        args=[LiteralValue(text=self._quote_path_if_needed(target))],
                        uninstall_only=True,
                    )
                )
            traces.append(
                RuleTrace(
                    rule_id="M-07",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Synthesized file list cleanup for {dest_str}",
                    doc_ref="Del",
                )
            )
            return "file", file_list_lines

        # 6. InstallTTF
        if kind == "installttf":
            font_file = (
                _unquote(self.translate_value_to_str(cmd.raw_args[1]))
                if len(cmd.raw_args) > 1
                else "*.ttf"
            )
            target = f"%Fonts%\\{font_file}"
            ttf_lines: list[SectionLine] = [
                Command(
                    name="Del",
                    args=[LiteralValue(text=self._quote_path_if_needed(target))],
                    uninstall_only=True,
                )
            ]
            return "file", ttf_lines

        # 7. MakeDir / CreateFolder
        if kind in ("makedir", "createfolder"):
            path_val = cmd.params.get("path") or (
                cmd.raw_args[0] if cmd.raw_args else None
            )
            path_str = _unquote(self.translate_value_to_str(path_val)) if path_val else ""
            if path_str:
                traces.append(
                    RuleTrace(
                        rule_id="M-08",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary=f"Synthesized directory removal: DelTree {path_str}",
                        doc_ref="DelTree / RmDir",
                    )
                )
                rd_lines: list[SectionLine] = [
                    Command(
                        name="DelTree",
                        args=[
                            LiteralValue(
                                text=self._quote_path_if_needed(path_str.rstrip("\\/"))
                            )
                        ],
                        uninstall_only=True,
                    )
                ]
                return "dir", rd_lines
            return "", []

        # 8. RegModify / RegModifyDWord -> Explicit deletion entry on uninstall
        if (
            kind
            in (
                "regmodify",
                "regmodifydword",
                "regmodifyqword",
                "regmodifymultisz",
            )
            and cmd.raw_args
        ):
            key_raw = self.translate_value_to_str(cmd.raw_args[0])
            key_str = _unquote(key_raw).rstrip("\\")
            parts = key_str.split("\\", 1)
            root_normalized = REG_ROOT_MAP.get(parts[0].lower(), parts[0])
            subkey = parts[1].lstrip("\\") if len(parts) > 1 else ""

            val_name: str | None = None
            if len(cmd.raw_args) >= 2:
                val_name = _unquote(self.translate_value_to_str(cmd.raw_args[1])).strip() or None

            self._collected_reg_entries.append(
                RegEntry(
                    root=root_normalized,
                    key=subkey,
                    value_name=val_name,
                    delete_value=val_name,
                    delete=True,
                    uninstall_only=True,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-10",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=(
                        f"Synthesized registry deletion: -{root_normalized},{subkey},"
                        f"{val_name or 'Key'}"
                    ),
                    doc_ref="[Reg:Product] -HKLM,...",
                )
            )
            return "", []

        return "", []
