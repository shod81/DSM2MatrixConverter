"""Rule transformation engine converting DSM IR models to Empirum Setup.inf AST."""

import re
from pathlib import Path
from typing import Literal, cast

from dsm2emp.ast.nodes import (
    CallStmt,
    Command,
    Comment,
    Comparison,
    Condition,
    CopyEntry,
    FunctionCall,
    GroupCondition,
    IfStmt,
    InfDocument,
    KeyValue,
    RegEntry,
    Section,
    SectionKind,
    SectionLine,
    SectionRef,
    SetRebootStmt,
    SetStmt,
    ShellEntry,
)
from dsm2emp.ast.values import LiteralValue, RegistryRef, Value, VarRef
from dsm2emp.parser.escript.lexer import parse_dsm_value, split_arguments, unquote
from dsm2emp.parser.ir import (
    IrCommand,
    IrComment,
    IrCompositeValue,
    IrCondition,
    IrFallbackVar,
    IrGoto,
    IrIf,
    IrLabel,
    IrLiteral,
    IrNestedVar,
    IrNode,
    IrPackage,
    IrTodo,
    IrValue,
    IrVarRef,
)
from dsm2emp.parser.nir import REG_ROOT_MAP, IrRegKey
from dsm2emp.rules.model import (
    Confidence,
    RuleSet,
    RuleTrace,
    TransformResult,
    count_constructs,
    weighted_average_confidence,
)
from dsm2emp.rules.msi import resolve_msi_guid
from dsm2emp.rules.uninstall import UninstallSynthesizer, normalize_payload_subpath

# Variable name translation table (DSM -> Empirum)
VAR_MAP = {
    # Source & Destination directories
    "src": "Src",
    "sourcedir": "Src",
    "dst": "App",
    "app": "App",
    "targetdir": "App",
    "installdir": "App",
    # System & Windows directories
    "windir": "Windows",
    "systemroot": "Windows",
    "winsysdir": "System",
    "systemdir": "System",
    "system": "System",
    # Program Files & Common Files
    "programfiles": "ProgramFilesDir",
    "programfilesdir": "ProgramFilesDir",
    "programfilesx86": "ProgramFilesDirx86",
    "programfilesdirx86": "ProgramFilesDirx86",
    "programfiles(x86)": "ProgramFilesDirx86",
    "commonfiles": "CommonFilesDir",
    "commonfilesdir": "CommonFilesDir",
    "commonprogramfilesdir": "CommonFilesDir",
    "commonfilesdirx86": "CommonFilesDirx86",
    "commonprogramfilesdirx86": "CommonFilesDirx86",
    # Profile & Shell directories
    "temp": "Temp",
    "tmp": "Temp",
    "allusersprofile": "CommonAppData",
    "programdata": "CommonAppData",
    "commonappdata": "CommonAppData",
    "allusersdesktop": "CommonDesktop",
    "commondesktop": "CommonDesktop",
    "allusersprograms": "CommonPrograms",
    "commonprograms": "CommonPrograms",
    "userdesktop": "Desktop",
    "desktop": "Desktop",
    "sendto": "Sendto",
    "personal": "Personal",
    # User & Machine identity
    "username": "WindowsUser",
    "windowsuser": "WindowsUser",
    "computername": "ComputerName",
    "userdomain": "DomainName",
    "domain": "DomainName",
    "domainname": "DomainName",
    # Package metadata & Execution status
    "exitcode": "ErrorLevel",
    "returncode": "ErrorLevel",
    "lastexitcode": "ErrorLevel",
    "errorlevel": "ErrorLevel",
    "packagename": "ProductName",
    "productname": "ProductName",
    "packagevendor": "DeveloperName",
    "developername": "DeveloperName",
    "packageversion": "Version",
    "version": "Version",
    "revision": "Revision",
}

# Central alias for payload subpath normalization
_normalize_payload_subpath = normalize_payload_subpath


def rewrite_extern_path(text: str) -> str:
    """Rewrite DSM extern$ and relative .\\ paths to Empirum %SRC%\\Files layout."""
    if not text:
        return text

    # 1. Rewrite extern$ references (e.g. .\extern$\foo or extern$\foo -> %SRC%\Files\foo)
    def _repl_extern(m: re.Match[str]) -> str:
        prefix = m.group(1)
        sep = "\\" if m.group(2) in ("\\", "/") else ""
        return f"{prefix}%SRC%\\Files{sep}"

    text = re.sub(
        r"(?i)(^|[\s\"'\(=,/|:])(?:\.[\\/])?extern\$([\\/]|$|(?=[\s\"'\),;]))",
        _repl_extern,
        text,
    )

    # 2. Rewrite quoted relative paths: ".\..." or '.\...'
    def _repl_quoted_double(m: re.Match[str]) -> str:
        return f'"{_normalize_payload_subpath(m.group(1))}"'

    text = re.sub(r'(?i)"\.[\\/]([^"]*)"', _repl_quoted_double, text)

    def _repl_quoted_single(m: re.Match[str]) -> str:
        return f"'{_normalize_payload_subpath(m.group(1))}'"

    text = re.sub(r"(?i)'\.[\\/]([^']*)'", _repl_quoted_single, text)

    # 3. Check if text as a whole starts with .\ or ./
    # Single path with spaces (.\Grass Valley\...) or command with args (.\setup.exe /s)
    clean = text.strip()
    if clean.startswith(".\\") or clean.startswith("./"):
        m_exe = re.match(r"(?i)^\.[\\/]([^\s\"'\),;]+\.(?:exe|msi|bat|cmd))\s+(.*)$", clean)
        if m_exe:
            exe_part = _normalize_payload_subpath(m_exe.group(1))
            args_part = m_exe.group(2)
            return f"{exe_part} {args_part}"
        else:
            return _normalize_payload_subpath(clean[2:])

    # 4. Unquoted relative path tokens inside text, preceded by delimiter
    def _repl_unquoted(m: re.Match[str]) -> str:
        prefix = m.group(1)
        sub = _normalize_payload_subpath(m.group(2))
        return f"{prefix}{sub}"

    text = re.sub(
        r"(?i)(^|[\s\(=,/|:])(?<!\.)\.[\\/]([^\s\"'\),;]+)",
        _repl_unquoted,
        text,
    )

    return text


class RuleEngine:
    """Transforms DSM IR structures to Empirum Setup.inf AST models."""

    def __init__(self, rule_set: RuleSet, allow_undocumented: bool = False) -> None:
        self.rules = rule_set
        self.allow_undocumented = allow_undocumented
        self._section_counter = 0
        self._collected_shell_entries: list[ShellEntry] = []
        self._collected_reg_entries: list[RegEntry] = []
        self._has_client_section: bool = False
        self._has_uninst_section: bool = False
        self._has_user_context: bool = False

    USER_PROFILE_VARS = {
        "appdata",
        "localappdata",
        "userdesktop",
        "personal",
        "sendto",
    }

    @staticmethod
    def _quote_path_if_needed(val_str: str) -> str:
        clean = unquote(val_str).strip("'\"")
        if not clean:
            return clean
        if clean.startswith('"') and clean.endswith('"'):
            return clean
        if any(c in clean for c in (" ", "\t", "\\", "/", "%")):
            return f'"{clean}"'
        return clean

    @staticmethod
    def _split_command_args(cmd_args: str) -> list[str]:
        """Split a command line arguments string into tokens, preserving quoted substrings."""
        if not cmd_args:
            return []
        tokens: list[str] = []
        current: list[str] = []
        in_quotes = False
        for ch in cmd_args:
            if ch == '"':
                in_quotes = not in_quotes
                current.append(ch)
            elif ch in (" ", "\t") and not in_quotes:
                if current:
                    tokens.append("".join(current))
                    current = []
            else:
                current.append(ch)
        if current:
            tokens.append("".join(current))
        return tokens

    def _next_section_name(self, prefix: str = "Set:Sub") -> str:
        """Generate unique section name for nested blocks."""
        self._section_counter += 1
        return f"{prefix}_{self._section_counter}"

    def translate_variable_name(self, name: str) -> str:
        """Translate DSM variable name to Empirum variable name."""
        name_lower = name.lower()
        if name_lower in self.USER_PROFILE_VARS:
            self._has_user_context = True
        return VAR_MAP.get(name_lower, name)

    def translate_value_to_str(self, val: IrValue) -> str:
        """Convert typed IrValue to string with Empirum variable syntax."""
        if isinstance(val, IrLiteral):
            return rewrite_extern_path(val.value)
        if isinstance(val, IrVarRef):
            mapped_name = self.translate_variable_name(val.name)
            return f"%{mapped_name}%"
        if isinstance(val, IrNestedVar):
            outer = self.translate_variable_name(val.outer)
            inner_str = self.translate_value_to_str(val.inner)
            return f"%%{outer}{inner_str}%%"
        if isinstance(val, IrFallbackVar):
            mapped_name = self.translate_variable_name(val.name)
            return f"%{mapped_name}%"
        if isinstance(val, IrCompositeValue):
            return rewrite_extern_path("".join(self.translate_value_to_str(p) for p in val.parts))
        return ""

    def translate_condition(self, cond: IrCondition) -> Condition:
        """Convert an IrCondition into an AST Condition node."""
        if cond.kind == "function":
            fn = cond.func_name or ""
            fn_lower = fn.lower()
            if fn_lower == "isrunningonx64":
                return Comparison(
                    left=VarRef(name="WindowsBits"),
                    relation="==",
                    right=LiteralValue(text="64"),
                )
            if fn_lower == "isrunningonserveros":
                return Comparison(
                    left=VarRef(name="OS.ProductType"),
                    relation="!=",
                    right=LiteralValue(text="1"),
                )
            if fn_lower == "islaptop":
                return Comparison(
                    left=VarRef(name="IsLaptop"),
                    relation="==",
                    right=LiteralValue(text="1"),
                )
            if fn_lower == "checkinstallmode":
                arg_val = (
                    self.translate_value_to_str(cond.func_args[0]).lower().strip("\"'")
                    if cond.func_args
                    else ""
                )
                if (arg_val == "imwkstapart" and not cond.negated) or (
                    arg_val == "imuninstall" and cond.negated
                ):
                    return Comparison(
                        left=LiteralValue(text="1"),
                        relation="==",
                        right=LiteralValue(text="1"),
                    )
                return Comparison(
                    left=LiteralValue(text="0"),
                    relation="==",
                    right=LiteralValue(text="1"),
                )

            # DSM Exist / FileExist -> Empirum DoesFileExist (or DoesPathExist if directory)
            if fn_lower in ("exist", "fileexist", "doesfileexist"):
                arg_str = (
                    unquote(self.translate_value_to_str(cond.func_args[0]))
                    if cond.func_args
                    else ""
                )
                clean_path = arg_str.strip("'\"")
                if re.match(r"(?i)^[a-zA-Z0-9_]+%\\", clean_path):
                    clean_path = "%" + clean_path
                fn_name = "DoesPathExist" if clean_path.endswith(("\\", "/")) else "DoesFileExist"
                if fn_name == "DoesPathExist":
                    clean_path = clean_path.rstrip("\\/")
                right_val = "0" if cond.negated else "1"
                return Comparison(
                    left=FunctionCall(function=fn_name, args=[LiteralValue(text=clean_path)]),
                    relation="==",
                    right=LiteralValue(text=right_val),
                )

            # DSM DirExist / PathExist -> Empirum DoesPathExist
            if fn_lower in ("direxist", "pathexist", "doespathexist"):
                arg_str = (
                    unquote(self.translate_value_to_str(cond.func_args[0]))
                    if cond.func_args
                    else ""
                )
                clean_path = arg_str.rstrip("\\/")
                right_val = "0" if cond.negated else "1"
                return Comparison(
                    left=FunctionCall(
                        function="DoesPathExist", args=[LiteralValue(text=clean_path)]
                    ),
                    relation="==",
                    right=LiteralValue(text=right_val),
                )

            # DSM RegKeyExists / RegValueExists / RegValue -> Empirum DoesRegKeyExist
            # (comma-separated root, path, and optional value)
            if fn_lower in (
                "regkeyexists",
                "regkeyexist",
                "doesregkeyexist",
                "regvalueexists",
                "doesregvalueexist",
                "regvalue",
            ):
                key_raw = self.translate_value_to_str(cond.func_args[0]) if cond.func_args else ""
                key_clean = unquote(key_raw).rstrip("\\")
                parts = key_clean.split("\\", 1)
                root = REG_ROOT_MAP.get(parts[0].lower(), parts[0])
                subkey = parts[1] if len(parts) > 1 else ""
                val_name = ""
                if len(cond.func_args) > 1:
                    val_name = unquote(self.translate_value_to_str(cond.func_args[1])).strip()
                emp_reg_key = f"{root},{subkey},{val_name}" if val_name else f"{root},{subkey}"
                right_val = "0" if cond.negated else "1"
                return Comparison(
                    left=FunctionCall(
                        function="DoesRegKeyExist", args=[LiteralValue(text=emp_reg_key)]
                    ),
                    relation="==",
                    right=LiteralValue(text=right_val),
                )

            # DSM MSIIsProductInstalled -> Empirum DoesRegKeyExist on Uninstall registry key
            if fn_lower == "msiisproductinstalled":
                guid_raw = self.translate_value_to_str(cond.func_args[0]) if cond.func_args else ""
                guid_clean = unquote(guid_raw).strip()
                emp_reg_key = (
                    f"HKLM,SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{guid_clean}"
                )
                right_val = "0" if cond.negated else "1"
                return Comparison(
                    left=FunctionCall(
                        function="DoesRegKeyExist", args=[LiteralValue(text=emp_reg_key)]
                    ),
                    relation="==",
                    right=LiteralValue(text=right_val),
                )

            # DSM ProcessExist / IsProcessRunning -> Empirum DoesProcessExist
            if fn_lower in ("processexist", "isprocessrunning", "doesprocessexist"):
                proc_str = (
                    unquote(self.translate_value_to_str(cond.func_args[0])).strip()
                    if cond.func_args
                    else ""
                )
                right_val = "0" if cond.negated else "1"
                return Comparison(
                    left=FunctionCall(
                        function="DoesProcessExist", args=[LiteralValue(text=proc_str)]
                    ),
                    relation="==",
                    right=LiteralValue(text=right_val),
                )

            args: list[Value | str] = [
                LiteralValue(text=self.translate_value_to_str(a)) for a in cond.func_args
            ]
            right_val = "0" if cond.negated else "1"
            return Comparison(
                left=FunctionCall(function=fn, args=args),
                relation="==",
                right=LiteralValue(text=right_val),
            )

        if cond.kind == "comparison" and cond.left is not None and cond.right is not None:
            left_str = self.translate_value_to_str(cond.left)
            right_str = self.translate_value_to_str(cond.right)
            op = cond.op or "=="
            if op == "=":
                op = "=="

            left_clean = unquote(left_str).strip()
            right_clean = unquote(right_str).strip()

            valid_rel: Literal["==", "=", "!=", "<>", "<", "<=", ">", ">="] = "=="
            if op in ("==", "=", "!=", "<>", "<", "<=", ">", ">="):
                valid_rel = cast(Literal["==", "=", "!=", "<>", "<", "<=", ">", ">="], op)

            # Check if left operand is RegValue(...) or a function call string
            # (e.g. DoesFileExist(...) or RegKeyExists(...))
            paren_idx = left_clean.find("(")
            if paren_idx != -1 and left_clean.endswith(")"):
                fn_candidate = left_clean[:paren_idx].strip()
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", fn_candidate):
                    args_body = left_clean[paren_idx + 1 : -1].strip()
                    raw_args = (
                        [parse_dsm_value(a) for a in split_arguments(args_body)]
                        if args_body
                        else []
                    )
                    # RegValue(...) reads registry value -> convert to RegistryRef
                    if fn_candidate.lower() == "regvalue" and raw_args:
                        key_raw = unquote(self.translate_value_to_str(raw_args[0])).rstrip("\\")
                        parts = key_raw.split("\\", 1)
                        root_norm = REG_ROOT_MAP.get(parts[0].lower(), parts[0])
                        subkey_norm = parts[1] if len(parts) > 1 else ""
                        val_name_norm = None
                        if len(raw_args) >= 2:
                            val_raw = unquote(self.translate_value_to_str(raw_args[1])).strip()
                            val_name_norm = val_raw if val_raw else None
                        reg_ref = RegistryRef(
                            root=root_norm,
                            key=subkey_norm,
                            value=val_name_norm,
                        )
                        return Comparison(
                            left=reg_ref,
                            relation=valid_rel,
                            right=LiteralValue(text=right_clean),
                        )

                    if right_clean in ("0", "1"):
                        is_neg = (right_clean == "0") if op in ("=", "==") else (right_clean == "1")
                        return self.translate_condition(
                            IrCondition(
                                raw=cond.raw,
                                kind="function",
                                negated=is_neg,
                                func_name=fn_candidate,
                                func_args=raw_args,
                            )
                        )

                    args_nodes: list[Value | str] = [
                        LiteralValue(text=unquote(self.translate_value_to_str(a))) for a in raw_args
                    ]
                    return Comparison(
                        left=FunctionCall(function=fn_candidate, args=args_nodes),
                        relation=valid_rel,
                        right=LiteralValue(text=right_clean),
                    )

            # Check if right operand is RegValue(...)
            r_paren_idx = right_clean.find("(")
            if r_paren_idx != -1 and right_clean.endswith(")"):
                r_fn = right_clean[:r_paren_idx].strip()
                if r_fn.lower() == "regvalue":
                    r_args_body = right_clean[r_paren_idx + 1 : -1].strip()
                    r_raw_args = (
                        [parse_dsm_value(a) for a in split_arguments(r_args_body)]
                        if r_args_body
                        else []
                    )
                    if r_raw_args:
                        key_raw = unquote(self.translate_value_to_str(r_raw_args[0])).rstrip("\\")
                        parts = key_raw.split("\\", 1)
                        root_norm = REG_ROOT_MAP.get(parts[0].lower(), parts[0])
                        subkey_norm = parts[1] if len(parts) > 1 else ""
                        val_name_norm = None
                        if len(r_raw_args) >= 2:
                            val_raw = unquote(self.translate_value_to_str(r_raw_args[1])).strip()
                            val_name_norm = val_raw if val_raw else None
                        reg_ref = RegistryRef(
                            root=root_norm,
                            key=subkey_norm,
                            value=val_name_norm,
                        )
                        return Comparison(
                            left=LiteralValue(text=left_clean),
                            relation=valid_rel,
                            right=reg_ref,
                        )

            def _parse_op_node(s: str) -> VarRef | LiteralValue:
                if s.startswith("%") and s.endswith("%") and s.count("%") == 2:
                    return VarRef(name=s[1:-1])
                return LiteralValue(text=s)

            left_node = _parse_op_node(left_str)
            right_node = _parse_op_node(right_str)

            valid_relation: Literal["==", "=", "!=", "<>", "<", "<=", ">", ">="] = "=="
            if op in ("==", "=", "!=", "<>", "<", "<=", ">", ">="):
                valid_relation = cast(Literal["==", "=", "!=", "<>", "<", "<=", ">", ">="], op)

            return Comparison(left=left_node, relation=valid_relation, right=right_node)

        # Fallback comparison
        return Comparison(
            left=LiteralValue(text=cond.raw),
            relation="==",
            right=LiteralValue(text="1"),
        )

    def _extract_user_context_commands(
        self, nodes: list[IrNode]
    ) -> tuple[list[IrNode], list[IrCommand]]:
        """Recursively pull DSM /TU (This User) commands out of the node tree.

        Returns (remaining_nodes, user_commands). User-context commands must not
        run in the machine pass, so they are removed from their original position
        (including inside If branches) and collected for [Set:Client].
        """
        remaining: list[IrNode] = []
        user_cmds: list[IrCommand] = []

        for node in nodes:
            if isinstance(node, IrCommand):
                if node.context == "user" and node.phase != "uninstall":
                    user_cmds.append(node)
                else:
                    remaining.append(node)
                continue
            if isinstance(node, IrIf):
                new_then, then_user = self._extract_user_context_commands(node.then_body)
                new_else: list[IrNode] = []
                else_user: list[IrCommand] = []
                if node.else_body:
                    new_else, else_user = self._extract_user_context_commands(node.else_body)
                user_cmds.extend(then_user)
                user_cmds.extend(else_user)
                if then_user or else_user:
                    node = node.model_copy(update={"then_body": new_then, "else_body": new_else})
                remaining.append(node)
            else:
                remaining.append(node)

        return remaining, user_cmds

    def _transform_command_list(
        self,
        nodes: list[IrNode],
        extra_sections: list[Section],
        traces: list[RuleTrace],
        todos: list[IrTodo],
        is_uninstall_section: bool = False,
        in_branch: bool = False,
    ) -> list[SectionLine]:
        """Transform a list of IR nodes into section lines and sidecar sections."""
        commands: list[SectionLine] = []

        for node in nodes:
            if isinstance(node, IrComment):
                if node.text.startswith("!"):
                    clean_text = node.text.lstrip("!").strip()
                elif node.text.lower().startswith("rem "):
                    clean_text = node.text[4:].strip()
                else:
                    clean_text = node.text.lstrip(";/ ").strip()
                commands.append(Comment(text=clean_text))
                continue

            if isinstance(node, IrTodo):
                todos.append(node)
                commands.append(Comment(text=f"Rem TODO: {node.message} ({node.raw})", style="rem"))
                traces.append(
                    RuleTrace(
                        rule_id="TODO",
                        source_line=node.src.line,
                        source_raw=node.raw,
                        confidence="todo",
                        target_summary=f"Unresolved TODO: {node.message}",
                        doc_ref="Unhandled DSM construct",
                    )
                )
                continue

            if isinstance(node, IrLabel):
                commands.append(Comment(text=f"Label: {node.name}"))
                traces.append(
                    RuleTrace(
                        rule_id="M-15",
                        source_line=node.src.line,
                        source_raw=node.src.raw,
                        confidence="high",
                        target_summary=f"Label {node.name}",
                        doc_ref="Label / GOTO",
                    )
                )
                continue

            if isinstance(node, IrGoto):
                commands.append(SectionRef(target=f"Set:{node.target}"))
                traces.append(
                    RuleTrace(
                        rule_id="M-15",
                        source_line=node.src.line,
                        source_raw=node.src.raw,
                        confidence="high",
                        target_summary=f"Jump to #{node.target}",
                        doc_ref="Label / GOTO",
                    )
                )
                continue

            if isinstance(node, IrIf):
                # Check for DSM CheckInstallMode execution context switches
                if node.conditions and len(node.conditions) == 1:
                    c = node.conditions[0]
                    fn = (c.func_name or "").lower()
                    if fn == "checkinstallmode" and c.func_args:
                        arg_str = self.translate_value_to_str(c.func_args[0]).lower().strip("\"'")

                        # Case 1: Workstation/Machine installation:
                        # - CheckInstallMode(imWkStaPart) [not negated]
                        # - not CheckInstallMode(imUninstall) [negated]
                        if (arg_str == "imwkstapart" and not c.negated) or (
                            arg_str == "imuninstall" and c.negated
                        ):
                            traces.append(
                                RuleTrace(
                                    rule_id="C-14",
                                    source_line=node.src.line,
                                    source_raw=node.src.raw,
                                    confidence="high",
                                    target_summary=(
                                        f"Unwrapped machine/install block '{node.src.raw}' into "
                                        "[Set:Product]"
                                    ),
                                    doc_ref="[Application] Machine/User",
                                )
                            )
                            commands.extend(
                                self._transform_command_list(
                                    node.then_body,
                                    extra_sections,
                                    traces,
                                    todos,
                                    is_uninstall_section=is_uninstall_section,
                                    in_branch=in_branch,
                                )
                            )
                            continue

                        # Case 2: User portion:
                        # - CheckInstallMode(imUserPart) [not negated]
                        if arg_str == "imuserpart" and not c.negated:
                            client_cmds = self._transform_command_list(
                                node.then_body,
                                extra_sections,
                                traces,
                                todos,
                                is_uninstall_section=False,
                                in_branch=True,
                            )
                            if client_cmds:
                                # Merge into an existing [Set:Client] (may already
                                # exist from /TU command routing) instead of
                                # emitting a duplicate section name.
                                existing_client_sec = next(
                                    (s for s in extra_sections if s.name == "Set:Client"),
                                    None,
                                )
                                if existing_client_sec:
                                    existing_client_sec.lines.extend(client_cmds)
                                else:
                                    extra_sections.append(
                                        Section(
                                            name="Set:Client",
                                            kind=SectionKind.WORK,
                                            lines=client_cmds,
                                        )
                                    )
                                self._has_client_section = True
                            traces.append(
                                RuleTrace(
                                    rule_id="C-14",
                                    source_line=node.src.line,
                                    source_raw=node.src.raw,
                                    confidence="high",
                                    target_summary=(
                                        f"Converted user part '{node.src.raw}' to [Set:Client], "
                                        "CLIENT"
                                    ),
                                    doc_ref="[Application] Machine/User",
                                )
                            )
                            continue

                        # Case 3: Uninstall mode:
                        # - CheckInstallMode(imUninstall) [not negated]
                        if arg_str == "imuninstall" and not c.negated:
                            uninst_cmds = self._transform_command_list(
                                node.then_body,
                                extra_sections,
                                traces,
                                todos,
                                is_uninstall_section=True,
                                in_branch=True,
                            )
                            if uninst_cmds:
                                # Reverse order: Empirum executes Set:Deinstallation
                                # bottom-to-top, so we emit in reverse DSM order.
                                # Sub-sections (SectionRef targets) are NOT reversed
                                # as they are executed forwards when jumped into.
                                uninst_cmds = list(reversed(uninst_cmds))
                                existing_uninst_sec = next(
                                    (s for s in extra_sections if s.name == "Set:Deinstallation"),
                                    None,
                                )
                                if existing_uninst_sec:
                                    existing_uninst_sec.lines.extend(uninst_cmds)
                                else:
                                    extra_sections.append(
                                        Section(
                                            name="Set:Deinstallation",
                                            kind=SectionKind.WORK,
                                            lines=uninst_cmds,
                                        )
                                    )
                                self._has_uninst_section = True
                            traces.append(
                                RuleTrace(
                                    rule_id="C-14",
                                    source_line=node.src.line,
                                    source_raw=node.src.raw,
                                    confidence="high",
                                    target_summary=(
                                        f"Converted uninstall block '{node.src.raw}' to "
                                        "[Set:Deinstallation] (reversed order)"
                                    ),
                                    doc_ref="[Application] Machine/User",
                                )
                            )
                            continue

                # Translate nested If/Else block
                if not node.conditions:
                    continue

                ast_cond: Condition
                if len(node.conditions) == 1:
                    ast_cond = self.translate_condition(node.conditions[0])
                else:
                    cond_op: Literal["|", "&"] = (
                        "&" if getattr(node, "condition_op", "|") == "&" else "|"
                    )
                    ast_cond = GroupCondition(
                        terms=[self.translate_condition(c) for c in node.conditions],
                        op=cond_op,
                    )

                if getattr(node, "is_mixed", False):
                    todos.append(
                        IrTodo(
                            raw=node.src.raw,
                            message="Mixed AND/OR condition in If statement requires manual review",
                            src=node.src,
                        )
                    )
                    traces.append(
                        RuleTrace(
                            rule_id="C-14",
                            source_line=node.src.line,
                            source_raw=node.src.raw,
                            confidence="todo",
                            target_summary=(
                                "Mixed AND/OR condition in If statement requires manual review"
                            ),
                            doc_ref="Conditions AND/OR",
                        )
                    )

                then_sec_name = self._next_section_name("Set:Then")
                then_cmds = self._transform_command_list(
                    node.then_body,
                    extra_sections,
                    traces,
                    todos,
                    is_uninstall_section=is_uninstall_section,
                    in_branch=True,
                )
                extra_sections.append(
                    Section(name=then_sec_name, kind=SectionKind.WORK, lines=then_cmds)
                )

                else_sec_name: str | None = None
                if node.else_body:
                    else_sec_name = self._next_section_name("Set:Else")
                    else_cmds = self._transform_command_list(
                        node.else_body,
                        extra_sections,
                        traces,
                        todos,
                        is_uninstall_section=is_uninstall_section,
                        in_branch=True,
                    )
                    extra_sections.append(
                        Section(name=else_sec_name, kind=SectionKind.WORK, lines=else_cmds)
                    )

                commands.append(
                    IfStmt(
                        condition=ast_cond,
                        then_target=then_sec_name,
                        else_target=else_sec_name,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-14",
                        source_line=node.src.line,
                        source_raw=node.src.raw,
                        confidence="high",
                        target_summary=f"If Then {then_sec_name}",
                        doc_ref="If ... Then ... Else ... EndIf",
                    )
                )
                continue

            if isinstance(node, IrCommand):
                cmd_lines = self._transform_single_command(
                    node,
                    extra_sections,
                    traces,
                    todos,
                    is_uninstall_section=is_uninstall_section,
                    in_branch=in_branch,
                )
                commands.extend(cmd_lines)

        return commands

    def _transform_single_command(
        self,
        cmd: IrCommand,
        extra_sections: list[Section],
        traces: list[RuleTrace],
        todos: list[IrTodo],
        is_uninstall_section: bool = False,
        in_branch: bool = False,
    ) -> list[SectionLine]:
        """Transform an individual IrCommand into Empirum AST section lines."""
        kind_lower = cmd.kind.lower()
        # Change 3: Commands in install sections never receive a '-' prefix.
        # Only commands in actual uninstall/delete sections receive uninstall_only=True.
        is_uninstall = is_uninstall_section
        result: list[SectionLine] = []

        # 1. ExecuteEx / Execute
        if kind_lower in ("executeex", "execute"):
            cmd_val = cmd.params.get("command")
            cmd_str = self.translate_value_to_str(cmd_val) if cmd_val else ""
            rule_id = "M-01" if kind_lower == "executeex" else "M-02"

            is_msi = "msiexec" in cmd_str.lower()
            if is_msi:
                rule_id = "M-03" if not is_uninstall else "M-04"

            # Parse program and arguments from command string
            if cmd_str.startswith('"'):
                end_quote = cmd_str.find('"', 1)
                if end_quote != -1:
                    prog = cmd_str[1:end_quote]
                    args_str = cmd_str[end_quote + 1 :].strip()
                else:
                    prog = cmd_str
                    args_str = ""
            else:
                # Check for executable extensions with spaces before arguments
                cmd_lower = cmd_str.lower()
                ext_match = None
                for ext in (".exe", ".cmd", ".bat", ".msi"):
                    idx = cmd_lower.find(ext)
                    if idx != -1:
                        after = cmd_str[idx + len(ext) :]
                        if not after or after[0] in (" ", "\t", '"', "'"):
                            ext_match = idx + len(ext)
                            break
                if ext_match is not None:
                    prog = cmd_str[:ext_match]
                    args_str = cmd_str[ext_match:].strip()
                else:
                    parts = cmd_str.split(maxsplit=1)
                    prog = parts[0] if parts else ""
                    args_str = parts[1] if len(parts) > 1 else ""

            # Split arguments into list of argument tokens
            arg_list: list[Value | str] = (
                [LiteralValue(text=a) for a in self._split_command_args(args_str)]
                if args_str
                else []
            )

            result.append(
                CallStmt(
                    name="CallHidden",
                    program=prog,
                    arguments=arg_list,
                    uninstall_only=is_uninstall,
                )
            )

            # Follow-up checks for MSI or ExecuteEx
            if is_msi or kind_lower == "executeex":
                # Check for reboot 3010
                result.append(
                    IfStmt(
                        condition=Comparison(
                            left=VarRef(name="ErrorLevel"),
                            relation="==",
                            right=LiteralValue(text="3010"),
                        ),
                        then_target="RebootRequired",
                    )
                )
                # Check for error != 0: MSI calls jump to the MSI error section,
                # plain unattend calls to the standard error sections so that
                # non-MSI packages do not pull in [AbortMSIInst].
                if is_msi:
                    error_target = "AbortMSIInst"
                else:
                    error_target = (
                        "Set:DeInstallationError" if is_uninstall else "Set:InstallationError"
                    )
                result.append(
                    IfStmt(
                        condition=Comparison(
                            left=VarRef(name="ErrorLevel"),
                            relation="!=",
                            right=LiteralValue(text="0"),
                        ),
                        then_target=error_target,
                    )
                )

            traces.append(
                RuleTrace(
                    rule_id=rule_id,
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Call {prog} {args_str}",
                    doc_ref="Call / ExecuteEx",
                )
            )
            return result

        # 2. Set variable
        if kind_lower == "set":
            name_val = cmd.params.get("name")
            val_val = cmd.params.get("value")
            name_str = self.translate_value_to_str(name_val) if name_val else ""
            val_str = self.translate_value_to_str(val_val) if val_val else ""
            clean_val = unquote(val_str)

            result.append(
                SetStmt(
                    variable=name_str,
                    value=LiteralValue(text=clean_val),
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-13",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Set {name_str}={clean_val}",
                    doc_ref="Set <Variable>=<Value>",
                )
            )
            return result

        # 3. Copy / InstallFile (Change 2: Hardened file copying via xcopy /S /H /E /V)
        if kind_lower in ("copy", "installfile"):
            src_val = cmd.params.get("source") or (
                cmd.raw_args[0] if len(cmd.raw_args) > 0 else None
            )
            dst_val = cmd.params.get("destination") or (
                cmd.raw_args[1] if len(cmd.raw_args) > 1 else None
            )
            src_str = unquote(self.translate_value_to_str(src_val)) if src_val else ""
            dst_str = unquote(self.translate_value_to_str(dst_val)) if dst_val else ""
            if (
                src_str
                and not src_str.startswith("%")
                and not re.match(r"^[a-zA-Z]:", src_str)
                and not src_str.startswith("\\\\")
            ):
                src_str = _normalize_payload_subpath(src_str)
            result.append(
                CallStmt(
                    name="CallHidden",
                    program="xcopy.exe",
                    arguments=[
                        LiteralValue(text=self._quote_path_if_needed(src_str)),
                        LiteralValue(text=self._quote_path_if_needed(dst_str)),
                        LiteralValue(text="/S"),
                        LiteralValue(text="/H"),
                        LiteralValue(text="/E"),
                        LiteralValue(text="/V"),
                        LiteralValue(text="/Y"),
                    ],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-05",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"xcopy {src_str} to {dst_str} (/S /H /E /V)",
                    doc_ref="CallHidden xcopy",
                )
            )
            return result

        # 4. Delete
        if kind_lower == "delete":
            path_val = cmd.params.get("path")
            path_str = self.translate_value_to_str(path_val) if path_val else ""
            clean_path = unquote(path_str).rstrip("\\/")
            if clean_path:
                # KB anti-pattern 3: Del cannot remove directories - use DelTree
                # for directory targets (same heuristic as UninstallSynthesizer).
                # DelTree with a trailing backslash fails (KB anti-pattern 2),
                # hence the rstrip above.
                is_dir = not re.search(r"\.[a-zA-Z0-9]{1,5}$", clean_path)
                cmd_name = "DelTree" if is_dir else "Del"
                result.append(
                    Command(
                        name=cmd_name,
                        args=[LiteralValue(text=clean_path)],
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-07",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary=f"{cmd_name} {clean_path}",
                        doc_ref="Del / DelTree",
                    )
                )
            return result

        # 5. MakeDir / CreateFolder
        if kind_lower in ("makedir", "createfolder"):
            path_val = cmd.params.get("path")
            path_str = self.translate_value_to_str(path_val) if path_val else ""
            result.append(
                Command(
                    name="MD",
                    args=[LiteralValue(text=path_str)],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-08",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"MD {path_str}",
                    doc_ref="MD/MkDir",
                )
            )
            return result

        # 6. RemoveDir / RemoveFolder
        if kind_lower in ("removedir", "removefolder"):
            path_val = cmd.params.get("path") or (cmd.raw_args[0] if cmd.raw_args else None)
            path_str = self.translate_value_to_str(path_val) if path_val else ""
            clean_path = unquote(path_str).rstrip("\\/")
            flags_val = cmd.params.get("flags") or (
                cmd.raw_args[1] if len(cmd.raw_args) > 1 else None
            )
            flags_str = self.translate_value_to_str(flags_val).lower() if flags_val else ""

            # RemoveFolder or recursive flags -> DelTree in Empirum (deletes folder + contents).
            # RemoveDir without recursive flags -> RD (deletes only empty directory).
            is_recursive = kind_lower == "removefolder" or "isubdirs" in flags_str
            cmd_name = "DelTree" if is_recursive else "RD"

            result.append(
                Command(
                    name=cmd_name,
                    args=[LiteralValue(text=clean_path)],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-08",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"{cmd_name} {clean_path}",
                    doc_ref="DelTree / RD",
                )
            )
            return result

        # 7. Sleep
        if kind_lower == "sleep":
            sec_val = cmd.params.get("seconds")
            sec_str = self.translate_value_to_str(sec_val) if sec_val else "1"
            try:
                ms = int(float(sec_str) * 1000)
            except ValueError:
                ms = 1000
            result.append(
                Command(
                    name="Sleep",
                    args=[LiteralValue(text=str(ms))],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-16",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Sleep {ms} ms",
                    doc_ref="Sleep <ms>",
                )
            )
            return result

        # 8. KillProcess
        if kind_lower == "killprocess":
            proc_val = cmd.params.get("process_name")
            proc_str = self.translate_value_to_str(proc_val) if proc_val else ""
            clean_proc = proc_str.strip("'\"")
            result.append(
                Command(
                    name="KillProcess",
                    args=[LiteralValue(text=clean_proc)],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-17",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"KillProcess {clean_proc}",
                    doc_ref="KillProcess",
                )
            )
            return result

        # 9. ExitProc / ExitProcEx
        if kind_lower in ("exitproc", "exitprocex"):
            msg_val = cmd.params.get("message")
            msg_str = self.translate_value_to_str(msg_val) if msg_val else ""
            clean_msg = msg_str.strip("'\"") or "Installation stopped"
            status_val = cmd.params.get("status")
            status_str = self.translate_value_to_str(status_val).lower() if status_val else ""

            if "success" in status_str or "ok" in status_str:
                result.append(Command(name="Exit", args=[], uninstall_only=is_uninstall))
            else:
                result.append(
                    Command(
                        name="Abort",
                        args=[LiteralValue(text=clean_msg)],
                        uninstall_only=is_uninstall,
                    )
                )

            traces.append(
                RuleTrace(
                    rule_id="M-19",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Abort/Exit: {clean_msg}",
                    doc_ref="Exit / Abort",
                )
            )
            return result

        # 10. WriteLogEntry
        if kind_lower == "writelogentry":
            msg_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            msg_str = self.translate_value_to_str(msg_val).strip("'\"")
            result.append(
                Command(
                    name="Echo",
                    args=[LiteralValue(text=msg_str)],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-20",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Echo {msg_str}",
                    doc_ref="Echo",
                )
            )
            return result

        # 11. CreateLink
        if kind_lower == "createlink":
            raw_arg0 = (
                unquote(self.translate_value_to_str(cmd.raw_args[0]))
                if cmd.raw_args
                else "%Desktop%\\Link"
            )
            raw_target = (
                unquote(self.translate_value_to_str(cmd.raw_args[1]))
                if len(cmd.raw_args) > 1
                else ""
            )

            # Determine link path:
            # If Arg 0 already starts with % or contains backslash, use directly
            # (e.g. %CommonPrograms%\Example Tools)
            if raw_arg0.startswith("%") or "\\" in raw_arg0:
                link_val = raw_arg0
            else:
                # Arg 0 is just a link name (e.g. 'ENAIO Client')
                # Check destination folder from Arg 4 (if provided in DSM)
                raw_folder = (
                    unquote(self.translate_value_to_str(cmd.raw_args[4])).strip("\\/")
                    if len(cmd.raw_args) > 4
                    else ""
                )
                folder_lower = raw_folder.lower()
                if (
                    folder_lower in ("start menu", "programs", "start menu/programs")
                    or not folder_lower
                ):
                    dest_dir = "%CommonPrograms%"
                elif folder_lower.startswith("start menu\\") or folder_lower.startswith(
                    "start menu/"
                ):
                    sub = raw_folder[11:].strip("\\/")
                    dest_dir = f"%CommonPrograms%\\{sub}" if sub else "%CommonPrograms%"
                elif folder_lower == "startup":
                    dest_dir = "%CommonStartup%"
                elif folder_lower == "desktop":
                    dest_dir = "%CommonDesktop%"
                else:
                    dest_dir = f"%CommonPrograms%\\{raw_folder}"
                link_val = f"{dest_dir}\\{raw_arg0}"

            # Strip .lnk suffix if present (Empirum does not use .lnk in [Shell:...])
            if link_val.lower().endswith(".lnk"):
                link_val = link_val[:-4]

            # Separate target program from embedded command line arguments if present
            ext_idx = -1
            for ext in (".exe", ".bat", ".cmd"):
                idx = raw_target.lower().find(ext)
                if (
                    idx != -1
                    and len(raw_target) > idx + len(ext)
                    and raw_target[idx + len(ext)] in (" ", "\t")
                ):
                    ext_idx = idx + len(ext)
                    break
            if ext_idx != -1:
                target_val = raw_target[:ext_idx].strip()
                target_args = raw_target[ext_idx:].strip()
            else:
                target_val = raw_target
                target_args = ""

            # Check Arg 2 (WorkingDir or Arguments in DSM):
            raw_arg2 = (
                unquote(self.translate_value_to_str(cmd.raw_args[2]))
                if len(cmd.raw_args) > 2
                else ""
            )
            if raw_arg2.startswith(("-", "/")):
                args_val = f"{target_args} {raw_arg2}".strip() if target_args else raw_arg2
                workdir_val = ""
            else:
                workdir_val = raw_arg2
                args_val = target_args

            # Check Arg 5 (optional WorkingDir in DSM)
            if len(cmd.raw_args) > 5:
                extra_wd = unquote(self.translate_value_to_str(cmd.raw_args[5])).strip()
                if extra_wd and not workdir_val:
                    workdir_val = extra_wd

            # Check Arg 3 (Icon path in DSM, e.g. "path\app.exe,0")
            raw_icon = (
                unquote(self.translate_value_to_str(cmd.raw_args[3]))
                if len(cmd.raw_args) > 3
                else ""
            )
            icon_file_val = ""
            icon_idx = 0
            if raw_icon:
                if "," in raw_icon:
                    parts = raw_icon.rsplit(",", 1)
                    icon_file_val = parts[0].strip().rstrip(",")
                    if parts[1].strip().isdigit():
                        icon_idx = int(parts[1].strip())
                else:
                    icon_file_val = raw_icon

            # Description is the link title (only when Arg 0 is a title, not an explicit path)
            desc_val = "" if (raw_arg0.startswith("%") or "\\" in raw_arg0) else raw_arg0

            self._collected_shell_entries.append(
                ShellEntry(
                    link=link_val,
                    command=target_val,
                    arguments=args_val,
                    workdir=workdir_val,
                    description=desc_val,
                    icon_file=icon_file_val,
                    icon_index=icon_idx,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-12",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary="CreateLink via [Shell:Product]",
                    doc_ref="[Shell:<Name>]",
                )
            )
            return result

        # 12. RegLoad
        if kind_lower == "regload":
            traces.append(
                RuleTrace(
                    rule_id="M-09",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary="RegLoad via [Reg:Product]",
                    doc_ref="[Reg:<Name>]",
                )
            )
            return result

        # 13. MSIUnInstallProduct
        if kind_lower == "msiuninstallproduct":
            guid_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            guid_str = unquote(self.translate_value_to_str(guid_val))
            guid = resolve_msi_guid(
                guid_str,
                package_root=getattr(self, "_package_root", None),
                media_files=getattr(self, "_media_files", None),
                msi_product_codes=getattr(self, "_msi_product_codes", None),
            )
            final_target = guid if guid else guid_str
            result.append(
                CallStmt(
                    name="CallHidden",
                    program="MsiExec.exe",
                    arguments=[
                        LiteralValue(text=f"/X{final_target}"),
                        LiteralValue(text="/qn"),
                        LiteralValue(text="/norestart"),
                    ],
                    uninstall_only=is_uninstall,
                )
            )
            self._has_reboot_section = True
            result.append(
                IfStmt(
                    condition=Comparison(
                        left=VarRef(name="ErrorLevel"),
                        relation="==",
                        right=LiteralValue(text="3010"),
                    ),
                    then_target="RebootRequired",
                )
            )
            result.append(
                IfStmt(
                    condition=Comparison(
                        left=VarRef(name="ErrorLevel"),
                        relation="!=",
                        right=LiteralValue(text="0"),
                    ),
                    then_target="AbortMSIInst",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-04",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"MSI Uninstall {guid_str}",
                    doc_ref="Call / UninstallString",
                )
            )
            return result

        # 14. MSIInstallProduct
        if kind_lower == "msiinstallproduct":
            msi_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            msi_str = unquote(self.translate_value_to_str(msi_val))
            if (
                msi_str
                and not msi_str.startswith("%")
                and not re.match(r"^[a-zA-Z]:", msi_str)
                and not msi_str.startswith("\\\\")
            ):
                msi_str = _normalize_payload_subpath(msi_str)
            args_list: list[Value | str] = [
                LiteralValue(text=f'/I"{msi_str}"'),
                LiteralValue(text="/qn"),
                LiteralValue(text="/norestart"),
            ]
            for extra_arg in cmd.raw_args[1:]:
                extra_str = unquote(self.translate_value_to_str(extra_arg)).strip()
                if extra_str.upper() in ("NORMAL", "MSIINSTMACH", "MSIINSTUSER"):
                    continue
                if extra_str:
                    args_list.append(LiteralValue(text=extra_str))

            result.append(
                CallStmt(
                    name="CallHidden",
                    program="MsiExec.exe",
                    arguments=args_list,
                    uninstall_only=is_uninstall,
                )
            )
            self._has_reboot_section = True
            result.append(
                IfStmt(
                    condition=Comparison(
                        left=VarRef(name="ErrorLevel"),
                        relation="==",
                        right=LiteralValue(text="3010"),
                    ),
                    then_target="RebootRequired",
                )
            )
            result.append(
                IfStmt(
                    condition=Comparison(
                        left=VarRef(name="ErrorLevel"),
                        relation="!=",
                        right=LiteralValue(text="0"),
                    ),
                    then_target="AbortMSIInst",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-03",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"MSI Install {msi_str}",
                    doc_ref="Call / MsiExec /I",
                )
            )
            return result

        # 15. EndProc
        if kind_lower == "endproc":
            traces.append(
                RuleTrace(
                    rule_id="M-19",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary="EndProc",
                    doc_ref="EndProc",
                )
            )
            return result

        # 16. RemoveLink
        if kind_lower == "removelink":
            link_name_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            link_name_str = unquote(self.translate_value_to_str(link_name_val))
            folder_val = cmd.raw_args[2] if len(cmd.raw_args) > 2 else IrLiteral(value="")
            folder_str = unquote(self.translate_value_to_str(folder_val)).strip("\\")
            shortcut = (
                f"{link_name_str}.lnk"
                if not link_name_str.lower().endswith(".lnk")
                else link_name_str
            )
            del_target = (
                f"%CommonStartMenu%\\{folder_str}\\{shortcut}"
                if folder_str
                else f"%CommonStartMenu%\\{shortcut}"
            )
            result.append(
                Command(
                    name="Del",
                    args=[LiteralValue(text=del_target)],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-12",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"RemoveLink {del_target}",
                    doc_ref="RemoveLink",
                )
            )
            return result

        # 17. InstallTTF
        if kind_lower == "installttf":
            src_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            src_str = unquote(self.translate_value_to_str(src_val)).rstrip("\\")
            font_file = (
                unquote(self.translate_value_to_str(cmd.raw_args[1]))
                if len(cmd.raw_args) > 1
                else ""
            )
            font_pattern = f"{src_str}\\{font_file}" if font_file else f"{src_str}\\*.ttf"
            result.append(
                CallStmt(
                    name="CallHidden",
                    program="xcopy.exe",
                    arguments=[
                        LiteralValue(text=self._quote_path_if_needed(font_pattern)),
                        LiteralValue(text=self._quote_path_if_needed("%Fonts%")),
                        LiteralValue(text="/S"),
                        LiteralValue(text="/H"),
                        LiteralValue(text="/E"),
                        LiteralValue(text="/V"),
                        LiteralValue(text="/Y"),
                    ],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-05",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"InstallTTF from {font_pattern} to %Fonts%",
                    doc_ref="CallHidden xcopy",
                )
            )
            return result

        # 18. InstallFileList / CopyFileList
        if kind_lower in ("installfilelist", "copyfilelist"):
            dest_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            dest_str = unquote(self.translate_value_to_str(dest_val))
            files = cmd.raw_args[1:]
            if files:
                for f in files:
                    file_str = unquote(self.translate_value_to_str(f))
                    if (
                        file_str
                        and not file_str.startswith("%")
                        and not re.match(r"^[a-zA-Z]:", file_str)
                        and not file_str.startswith("\\\\")
                    ):
                        file_str = _normalize_payload_subpath(file_str)
                    result.append(
                        CallStmt(
                            name="CallHidden",
                            program="xcopy.exe",
                            arguments=[
                                LiteralValue(text=self._quote_path_if_needed(file_str)),
                                LiteralValue(text=self._quote_path_if_needed(dest_str)),
                                LiteralValue(text="/S"),
                                LiteralValue(text="/H"),
                                LiteralValue(text="/E"),
                                LiteralValue(text="/V"),
                                LiteralValue(text="/Y"),
                            ],
                            uninstall_only=is_uninstall,
                        )
                    )
            else:
                result.append(
                    CallStmt(
                        name="CallHidden",
                        program="xcopy.exe",
                        arguments=[
                            LiteralValue(text=self._quote_path_if_needed("%SRC%\\Files\\*.*")),
                            LiteralValue(text=self._quote_path_if_needed(dest_str)),
                            LiteralValue(text="/S"),
                            LiteralValue(text="/H"),
                            LiteralValue(text="/E"),
                            LiteralValue(text="/V"),
                            LiteralValue(text="/Y"),
                        ],
                        uninstall_only=is_uninstall,
                    )
                )
            traces.append(
                RuleTrace(
                    rule_id="M-05",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"xcopy files to {dest_str} (/S /H /E /V)",
                    doc_ref="CallHidden xcopy",
                )
            )
            return result

        # 19. RegDeleteKey
        if kind_lower == "regdeletekey":
            if cmd.raw_args:
                key_raw = self.translate_value_to_str(cmd.raw_args[0])
                key_str = unquote(key_raw).rstrip("\\")
                parts = key_str.split("\\", 1)
                root_normalized = REG_ROOT_MAP.get(parts[0].lower(), parts[0])
                subkey = parts[1] if len(parts) > 1 else ""

                val_name: str | None = None
                if len(cmd.raw_args) >= 2:
                    v_raw = unquote(self.translate_value_to_str(cmd.raw_args[1])).strip()
                    if v_raw:
                        val_name = v_raw

                # The '-' prefix in [Reg:Product] signals uninstall-time deletion.
                # RegDeleteKey in an install section should NOT produce '-'; only
                # in an uninstall section does it get the delete flag.
                if is_uninstall:
                    self._collected_reg_entries.append(
                        RegEntry(
                            root=root_normalized,
                            key=subkey,
                            delete_value=val_name,
                            delete=True,
                            uninstall_only=True,
                        )
                    )
                    traces.append(
                        RuleTrace(
                            rule_id="M-11",
                            source_line=cmd.src.line,
                            source_raw=cmd.src.raw,
                            confidence="high",
                            target_summary=(
                                f"RegDeleteKey {key_str} ({val_name or 'Key'}) [Uninstall]"
                            ),
                            doc_ref="[Reg:Product] -HKLM,...",
                        )
                    )
                else:
                    # In install context, [Reg:Product] '-' entries are only evaluated by Setup.exe
                    # on deinstallation. To delete registry keys or values procedurally during
                    # installation, invoke Windows built-in reg.exe via CallHidden.
                    full_reg_key = f"{root_normalized}\\{subkey}" if subkey else root_normalized
                    args: list[Value | str] = [
                        LiteralValue(text="delete"),
                        LiteralValue(text=f'"{full_reg_key}"'),
                    ]
                    if val_name:
                        args.extend(
                            [
                                LiteralValue(text="/v"),
                                LiteralValue(text=f'"{val_name}"'),
                            ]
                        )
                    args.append(LiteralValue(text="/f"))
                    result.append(
                        CallStmt(
                            name="CallHidden",
                            program="reg.exe",
                            arguments=args,
                            uninstall_only=False,
                        )
                    )
                    traces.append(
                        RuleTrace(
                            rule_id="M-11",
                            source_line=cmd.src.line,
                            source_raw=cmd.src.raw,
                            confidence="high",
                            target_summary=(
                                f"CallHidden reg.exe delete {full_reg_key}"
                                + (f" /v {val_name}" if val_name else "")
                            ),
                            doc_ref="CallHidden reg.exe delete",
                        )
                    )
                return result

        # 20. RegModify / RegModifyDWord / RegModifyQWord / RegModifyMultiSZ
        if kind_lower in ("regmodify", "regmodifydword", "regmodifyqword", "regmodifymultisz"):
            if cmd.raw_args:
                key_raw = self.translate_value_to_str(cmd.raw_args[0])
                key_str = unquote(key_raw).rstrip("\\")
                parts = key_str.split("\\", 1)
                root_normalized = REG_ROOT_MAP.get(parts[0].lower(), parts[0])
                subkey = parts[1] if len(parts) > 1 else ""

                val_name = None
                if len(cmd.raw_args) >= 2:
                    raw_vname = unquote(self.translate_value_to_str(cmd.raw_args[1])).strip()
                    val_name = raw_vname if raw_vname else None

                val_data = ""
                if len(cmd.raw_args) >= 3:
                    val_data = unquote(self.translate_value_to_str(cmd.raw_args[2])).strip()

                # Determine type flag and reg.exe type name
                if kind_lower == "regmodifydword":
                    reg_type_name = "REG_DWORD"
                    type_flag = "0x00010001"
                elif kind_lower == "regmodifyqword":
                    reg_type_name = "REG_QWORD"
                    type_flag = "0x00040001"
                elif kind_lower == "regmodifymultisz":
                    reg_type_name = "REG_MULTI_SZ"
                    type_flag = "0x00010000"
                else:  # regmodify
                    reg_type_name = "REG_SZ"
                    type_flag = "0x00000000"
                    if len(cmd.raw_args) >= 4:
                        type_arg = (
                            unquote(self.translate_value_to_str(cmd.raw_args[3])).strip().upper()
                        )
                        if "DWORD" in type_arg:
                            reg_type_name = "REG_DWORD"
                            type_flag = "0x00010001"
                        elif "BINARY" in type_arg:
                            reg_type_name = "REG_BINARY"
                            type_flag = "0x00000001"
                        elif "MULTI" in type_arg:
                            reg_type_name = "REG_MULTI_SZ"
                            type_flag = "0x00010000"
                        elif "EXPAND" in type_arg:
                            reg_type_name = "REG_EXPAND_SZ"
                            type_flag = "0x00020000"

                if in_branch or is_uninstall:
                    # Sequential execution via CallHidden reg.exe add:
                    # Guarantees that inside If/Else branches or uninstall blocks,
                    # the change is executed ONLY when that branch is reached.
                    full_reg_key = f"{root_normalized}\\{subkey}" if subkey else root_normalized
                    args = [
                        LiteralValue(text="add"),
                        LiteralValue(text=f'"{full_reg_key}"'),
                    ]
                    if val_name:
                        args.extend(
                            [
                                LiteralValue(text="/v"),
                                LiteralValue(text=f'"{val_name}"' if " " in val_name else val_name),
                            ]
                        )
                    else:
                        args.append(LiteralValue(text="/ve"))

                    data_quoted = f'"{val_data}"' if " " in val_data or not val_data else val_data
                    args.extend(
                        [
                            LiteralValue(text="/t"),
                            LiteralValue(text=reg_type_name),
                            LiteralValue(text="/d"),
                            LiteralValue(text=data_quoted),
                            LiteralValue(text="/f"),
                        ]
                    )
                    if cmd.x64_redirect_off:
                        args.append(LiteralValue(text="/reg:64"))

                    result.append(
                        CallStmt(
                            name="CallHidden",
                            program="reg.exe",
                            arguments=args,
                            uninstall_only=is_uninstall,
                        )
                    )
                    traces.append(
                        RuleTrace(
                            rule_id="M-10",
                            source_line=cmd.src.line,
                            source_raw=cmd.src.raw,
                            confidence="high",
                            target_summary=(
                                f"CallHidden reg.exe add {full_reg_key} -> "
                                f"{val_name or '@'}={val_data} ({reg_type_name})"
                            ),
                            doc_ref="CallHidden reg.exe add",
                        )
                    )
                    return result
                else:
                    self._collected_reg_entries.append(
                        RegEntry(
                            root=root_normalized,
                            key=subkey,
                            value_name=val_name,
                            type_flag=type_flag,
                            data=[LiteralValue(text=val_data)],
                            uninstall_only=is_uninstall,
                        )
                    )
                    traces.append(
                        RuleTrace(
                            rule_id="M-10",
                            source_line=cmd.src.line,
                            source_raw=cmd.src.raw,
                            confidence="high",
                            target_summary=(
                                f"{cmd.kind} {key_str} -> {val_name}={val_data} ({type_flag})"
                            ),
                            doc_ref="[Reg:Product]",
                        )
                    )
                    return []

        # 21. MSIApplyPatch
        if kind_lower == "msiapplypatch":
            msp_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            msp_str = unquote(self.translate_value_to_str(msp_val))
            result.append(
                CallStmt(
                    name="CallHidden",
                    program="MsiExec.exe",
                    arguments=[
                        LiteralValue(text=f'/p "{msp_str}"'),
                        LiteralValue(text="/qn"),
                        LiteralValue(text="/norestart"),
                    ],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-03",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"MSI Apply Patch {msp_str}",
                    doc_ref="Call / MsiExec /p",
                )
            )
            return result

        # 22. CallScript
        if kind_lower == "callscript":
            script_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            script_str = unquote(self.translate_value_to_str(script_val))
            if script_str.lower().endswith(".ps1"):
                result.append(
                    CallStmt(
                        name="CallHidden",
                        program="powershell.exe",
                        arguments=[
                            LiteralValue(text="-ExecutionPolicy"),
                            LiteralValue(text="Bypass"),
                            LiteralValue(text="-NoProfile"),
                            LiteralValue(text="-File"),
                            LiteralValue(text=f'"{script_str}"'),
                        ],
                        uninstall_only=is_uninstall,
                    )
                )
            else:
                result.append(
                    CallStmt(
                        name="CallHidden",
                        program="cscript.exe",
                        arguments=[
                            LiteralValue(text="//nologo"),
                            LiteralValue(text=f'"{script_str}"'),
                        ],
                        uninstall_only=is_uninstall,
                    )
                )
            traces.append(
                RuleTrace(
                    rule_id="M-01",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"CallScript {script_str}",
                    doc_ref="Call Script",
                )
            )
            return result

        # 23. ClearRestartFlags
        if kind_lower == "clearrestartflags":
            traces.append(
                RuleTrace(
                    rule_id="M-18",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary="ClearRestartFlags",
                    doc_ref="ClearRestartFlags",
                )
            )
            return result

        # 24. UninstallService
        if kind_lower == "uninstallservice":
            svc_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            svc_str = unquote(self.translate_value_to_str(svc_val))
            result.append(
                CallStmt(
                    name="CallHidden",
                    program="sc.exe",
                    arguments=[
                        LiteralValue(text="delete"),
                        LiteralValue(text=f'"{svc_str}"'),
                    ],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-01",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"sc delete {svc_str}",
                    doc_ref="UninstallService",
                )
            )
            return result

        # 25. ChangeNTFSSecurity (Group B)
        if kind_lower == "changentfssecurity":
            path_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            path_str = unquote(self.translate_value_to_str(path_val))
            sid_str = "S-1-5-11"
            perms_str = "(OI)(CI)M"
            if len(cmd.raw_args) >= 2:
                for arg in cmd.raw_args[1:]:
                    a_str = unquote(self.translate_value_to_str(arg)).strip()
                    if a_str.upper().startswith("S-1-"):
                        sid_str = a_str
                    elif a_str.upper() in ("DRWX", "RWX", "RX", "R", "W", "F"):
                        if a_str.upper() == "DRWX":
                            perms_str = "(OI)(CI)M"
                        elif a_str.upper() == "RX":
                            perms_str = "(OI)(CI)RX"
                        elif a_str.upper() == "F":
                            perms_str = "(OI)(CI)F"

            result.append(
                CallStmt(
                    name="CallHidden",
                    program="icacls.exe",
                    arguments=[
                        LiteralValue(text=f'"{path_str}"'),
                        LiteralValue(text="/grant"),
                        LiteralValue(text=f"*{sid_str}:{perms_str}"),
                        LiteralValue(text="/T"),
                        LiteralValue(text="/C"),
                    ],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-01",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"icacls {path_str} grant *{sid_str}:{perms_str}",
                    doc_ref="ChangeNTFSSecurity -> icacls",
                )
            )
            return result

        # M-28: CommitChangesToServer (redundant in Empirum, sync handled by Agent)
        if kind_lower == "commitchangestoserver":
            result.append(
                Comment(
                    text="; Rem Info (M-28): CommitChangesToServer - "
                    "DSM-Infrastruktur; in Empirum nicht erforderlich",
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-28",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary="CommitChangesToServer - redundant in Empirum",
                    doc_ref="Ivanti Lifecycle / M-28",
                    notes=["DSM-Serverkommunikation; in Empirum vom Agent automatisch verwaltet."],
                )
            )
            return result

        # M-28: ChangeSwAssignment (Software policy assignment)
        if kind_lower == "changeswassignment":
            pkg_guid = ""
            if cmd.raw_args:
                pkg_guid = unquote(self.translate_value_to_str(cmd.raw_args[0]))
            summary = (
                f"ChangeSwAssignment('{pkg_guid}') - "
                "Paket-Abhaengigkeit in Empirum Console definieren"
                if pkg_guid
                else "ChangeSwAssignment - Paket-Abhaengigkeit in Empirum Console definieren"
            )
            result.append(
                Comment(
                    text=f"; Rem Info (M-28): {summary}",
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-28",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=summary,
                    doc_ref="Ivanti Lifecycle / M-28",
                    notes=[
                        "Software-Zuweisung in Empirum ueber "
                        "Zuweisungsgruppen oder Abhaengigkeiten."
                    ],
                )
            )
            return result

        # M-21: RunAsEx
        if kind_lower == "runasex":
            prog_val = cmd.raw_args[0] if len(cmd.raw_args) > 0 else IrLiteral(value="")
            prog_str = unquote(self.translate_value_to_str(prog_val))
            param_val = cmd.raw_args[1] if len(cmd.raw_args) > 1 else None
            param_str = unquote(self.translate_value_to_str(param_val)) if param_val else ""
            flags_val = cmd.raw_args[6] if len(cmd.raw_args) > 6 else None
            flags_str = self.translate_value_to_str(flags_val) if flags_val else ""

            is_sis = "rausesisaccount" in flags_str.lower()
            arg_list = (
                [LiteralValue(text=a) for a in self._split_command_args(param_str)]
                if param_str
                else []
            )

            if is_sis or not flags_str:
                result.append(
                    CallStmt(
                        name="CallHidden",
                        program=prog_str,
                        arguments=arg_list,
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-21",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary=(
                            f"Call '{prog_str}' (RunAsEx raUseSisAccount -> Machine Context)"
                        ),
                        doc_ref="CallRunAs / M-21",
                        notes=[
                            "RunAsEx mit raUseSisAccount im Standard-Maschinenkontext ausgefuehrt."
                        ],
                    )
                )
                return result

            user_val = cmd.raw_args[2] if len(cmd.raw_args) > 2 else IrLiteral(value="")
            user_str = unquote(self.translate_value_to_str(user_val)).strip()
            if not user_str or user_str.lower() in (
                "rausesisaccount",
                "standard",
                "system",
                "localsystem",
            ):
                result.append(
                    CallStmt(
                        name="CallHidden",
                        program=prog_str,
                        arguments=arg_list,
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-21",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary=(
                            f"Call '{prog_str}' (RunAsEx ohne Benutzer -> Machine Context)"
                        ),
                        doc_ref="CallRunAs / M-21",
                        notes=[
                            "RunAsEx ohne spezifischen Benutzer im Standard-Maschinenkontext "
                            "ausgefuehrt."
                        ],
                    )
                )
                return result

            result.append(
                Comment(
                    text=f"Rem TODO (M-21): RunAsEx '{prog_str}' als Benutzer '{user_str}' pruefen",
                    style="rem",
                )
            )
            todos.append(
                IrTodo(
                    raw=cmd.src.raw,
                    message=f"Ausführung unter anderem Benutzer ({user_str})",
                    src=cmd.src,
                    confidence=0.5,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-21",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="medium",
                    target_summary=f"TODO: RunAsEx unter Benutzer '{user_str}'",
                    doc_ref="CallRunAs / M-21",
                )
            )
            return result

        # M-24: CallScriptAs
        if kind_lower == "callscriptas":
            script_val = cmd.params.get("script") or (
                cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            )
            script_str = unquote(self.translate_value_to_str(script_val))
            cs_args_val = cmd.params.get("arguments") or (
                cmd.raw_args[1] if len(cmd.raw_args) > 1 else None
            )
            cs_args_str = unquote(self.translate_value_to_str(cs_args_val)) if cs_args_val else ""
            cs_user_val = cmd.params.get("user") or (
                cmd.raw_args[2] if len(cmd.raw_args) > 2 else None
            )
            user_str = (
                unquote(self.translate_value_to_str(cs_user_val)).strip() if cs_user_val else ""
            )
            flags_val = cmd.params.get("flags") or (
                cmd.raw_args[4] if len(cmd.raw_args) > 4 else None
            )
            flags_str = self.translate_value_to_str(flags_val).lower() if flags_val else ""

            is_sis = "rausesisaccount" in flags_str
            # If no user or raUseSisAccount, run in machine context
            if (
                is_sis
                or not user_str
                or user_str.lower() in ("standard", "system", "localsystem", "rausesisaccount")
            ):
                script_lower = script_str.lower()
                arg_tokens: list[Value | str] = []
                if script_lower.endswith(".ps1"):
                    prog = "powershell.exe"
                    arg_tokens = [
                        LiteralValue(text="-ExecutionPolicy"),
                        LiteralValue(text="Bypass"),
                        LiteralValue(text="-NoProfile"),
                        LiteralValue(text="-File"),
                        LiteralValue(text=self._quote_path_if_needed(script_str)),
                    ]
                    if cs_args_str:
                        arg_tokens.extend(
                            [LiteralValue(text=a) for a in self._split_command_args(cs_args_str)]
                        )
                elif script_lower.endswith(".vbs"):
                    prog = "cscript.exe"
                    arg_tokens = [
                        LiteralValue(text="//nologo"),
                        LiteralValue(text=self._quote_path_if_needed(script_str)),
                    ]
                    if cs_args_str:
                        arg_tokens.extend(
                            [LiteralValue(text=a) for a in self._split_command_args(cs_args_str)]
                        )
                else:
                    prog = script_str
                    if cs_args_str:
                        arg_tokens = [
                            LiteralValue(text=a) for a in self._split_command_args(cs_args_str)
                        ]

                result.append(
                    CallStmt(
                        name="CallHidden",
                        program=prog,
                        arguments=arg_tokens,
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-24",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary=(
                            f"Call '{prog}' (CallScriptAs '{script_str}' "
                            "im Standard-Maschinenkontext)"
                        ),
                        doc_ref="CallScriptAs / M-24",
                        notes=[
                            "CallScriptAs mit raUseSisAccount im Standard-Maschinenkontext "
                            "ausgefuehrt."
                        ],
                    )
                )
                return result

            # Genuine user impersonation
            result.append(
                Comment(
                    text=(
                        f"Rem TODO (M-24): CallScriptAs '{script_str}' als Benutzer "
                        f"'{user_str}' pruefen"
                    ),
                    style="rem",
                )
            )
            todos.append(
                IrTodo(
                    raw=cmd.src.raw,
                    message=f"Skript im Kontext eines Benutzers aufrufen ({user_str})",
                    src=cmd.src,
                    confidence=0.5,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-24",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="medium",
                    target_summary=f"TODO: CallScriptAs unter Benutzer '{user_str}'",
                    doc_ref="CallScriptAs / M-24",
                )
            )
            return result

        # Stray / orphaned script fragments (e.g. 'False' or 'Name' without args)
        if kind_lower in ("false", "true", "name", "none") and not cmd.raw_args:
            raw_text = cmd.src.raw.strip()
            result.append(
                Comment(
                    text=f"; Rem Info: Verwaistes Skriptfragment ignoriert: '{raw_text}'",
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-00",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Ignored dangling script fragment '{raw_text}'",
                    doc_ref="Skriptbereinigung",
                    notes=["Verwaistes Fragment aus auskommentiertem DSM-Skriptblock ignoriert."],
                )
            )
            return result

        # IncrementVar / Increment
        if kind_lower in ("incrementvar", "increment"):
            var_name = (
                unquote(self.translate_value_to_str(cmd.raw_args[0])) if cmd.raw_args else "Var"
            )
            step = (
                unquote(self.translate_value_to_str(cmd.raw_args[1]))
                if len(cmd.raw_args) > 1
                else ""
            )
            args_list = [VarRef(name=var_name)]
            if step and step != "1":
                args_list.append(LiteralValue(text=step))
            result.append(
                Command(
                    name="Increment",
                    args=args_list,
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-13",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=(
                        f"Increment ({var_name}{f', {step}' if step and step != '1' else ''})"
                    ),
                    doc_ref="Increment",
                )
            )
            return result

        # DeleteFileList -> Del for each file in raw_args
        if kind_lower == "deletefilelist":
            for file_arg in cmd.raw_args:
                f_str = unquote(self.translate_value_to_str(file_arg)).rstrip("\\/")
                if f_str:
                    is_dir = not re.search(r"\.[a-zA-Z0-9]{1,5}$", f_str)
                    cmd_name = "DelTree" if is_dir else "Del"
                    result.append(
                        Command(
                            name=cmd_name,
                            args=[LiteralValue(text=f_str)],
                            uninstall_only=is_uninstall,
                        )
                    )
            if not result:
                result.append(
                    Comment(
                        text="; Rem Info: DeleteFileList verarbeitet",
                        style="rem",
                    )
                )
            traces.append(
                RuleTrace(
                    rule_id="M-07",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary="DeleteFileList -> Del",
                    doc_ref="Del <File>",
                )
            )
            return result

        # ModifyObjectProperty (DSM computer inventory metadata - redundant in Empirum)
        if kind_lower == "modifyobjectproperty":
            prop_name = (
                unquote(self.translate_value_to_str(cmd.raw_args[1]))
                if len(cmd.raw_args) > 1
                else ""
            )
            prop_val = (
                unquote(self.translate_value_to_str(cmd.raw_args[2]))
                if len(cmd.raw_args) > 2
                else ""
            )
            result.append(
                Comment(
                    text=(
                        f"; Rem Info: DSM-Objekteigenschaft '{prop_name}'={prop_val} "
                        "(in Empirum nicht erforderlich)"
                    ),
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-28",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=(
                        f"ModifyObjectProperty({prop_name}={prop_val}) - redundant in Empirum"
                    ),
                    doc_ref="Ivanti Lifecycle",
                    notes=[
                        "DSM-Rechnerobjekteigenschaft; in Empirum durch "
                        "Inventory/Registry abgebildet."
                    ],
                )
            )
            return result

        # AddIni -> [Ini:Product] Info
        if kind_lower == "addini":
            ini_path = unquote(self.translate_value_to_str(cmd.raw_args[0])) if cmd.raw_args else ""
            result.append(
                Comment(
                    text=(
                        f"; Rem Info: AddIni '{ini_path}' - "
                        "INI-Sektionen in [Ini:Product] uebertragen"
                    ),
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-12",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"AddIni '{ini_path}'",
                    doc_ref="[Ini:<Name>]",
                )
            )
            return result

        # RegLoadEx / RegLoad -> NIR Snapshot in [Reg:Product]
        if kind_lower in ("regloadex", "regload"):
            reg_file = unquote(self.translate_value_to_str(cmd.raw_args[0])) if cmd.raw_args else ""
            result.append(
                Comment(
                    text=(
                        f"; Rem Info: RegLoadEx '{reg_file}' (Inhalt in [Reg:Product] uebertragen)"
                    ),
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-09",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"RegLoadEx '{reg_file}' -> [Reg:Product]",
                    doc_ref="[Reg:<Name>]",
                    notes=["NIR-Snapshot wird vollstaendig in [Reg:Product] serialisiert."],
                )
            )
            return result

        # StartService / StopService
        if kind_lower in ("startservice", "stopservice"):
            svc_val = cmd.params.get("service_name") or (
                cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            )
            svc_name = unquote(self.translate_value_to_str(svc_val))
            cmd_name = "StartService" if kind_lower == "startservice" else "StopService"
            result.append(
                Command(
                    name=cmd_name,
                    args=[LiteralValue(text=svc_name)],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-22",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"{cmd_name} {svc_name}",
                    doc_ref="Dienste",
                )
            )
            return result

        # InstallService
        if kind_lower == "installservice":
            svc_val = cmd.params.get("service_name") or (
                cmd.raw_args[1] if len(cmd.raw_args) > 1 else IrLiteral(value="")
            )
            svc_name = unquote(self.translate_value_to_str(svc_val))
            cmd_val = cmd.params.get("command") or (
                cmd.raw_args[2] if len(cmd.raw_args) > 2 else IrLiteral(value="")
            )
            cmd_str = unquote(self.translate_value_to_str(cmd_val))
            result.append(
                Comment(
                    text=f"; Rem Info: InstallService '{svc_name}' (Befehl: {cmd_str})",
                    style="rem",
                )
            )
            if cmd_str:
                result.append(
                    CallStmt(
                        name="CallHidden",
                        program="cmd.exe",
                        arguments=[
                            LiteralValue(text=f'/c sc create "{svc_name}" binPath= "{cmd_str}"')
                        ],
                        uninstall_only=is_uninstall,
                    )
                )
            traces.append(
                RuleTrace(
                    rule_id="M-22-INST",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"InstallService '{svc_name}'",
                    doc_ref="Dienste",
                )
            )
            return result

        # CreateInternetLink -> URL shortcut
        if kind_lower == "createinternetlink":
            link_name = (
                unquote(self.translate_value_to_str(cmd.raw_args[0])) if cmd.raw_args else "Link"
            )
            url_str = (
                unquote(self.translate_value_to_str(cmd.raw_args[1]))
                if len(cmd.raw_args) > 1
                else ""
            )
            result.append(
                Comment(
                    text=f"; Rem Info: CreateInternetLink '{link_name}' -> '{url_str}'",
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-10-URL",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"CreateInternetLink '{link_name}' -> '{url_str}'",
                    doc_ref="Verknuepfungen",
                )
            )
            return result

        # RegReadValue / RegReadValueEx / RegRead -> Set Var=%%%Key,ValueName%%%
        if kind_lower in ("regreadvalue", "regreadvalueex", "regread"):
            key_val = cmd.raw_args[0] if len(cmd.raw_args) > 0 else IrLiteral(value="")
            rr_val_name = cmd.raw_args[1] if len(cmd.raw_args) > 1 else IrLiteral(value="")
            rr_var_name = cmd.raw_args[2] if len(cmd.raw_args) > 2 else IrLiteral(value="")
            key_str = unquote(self.translate_value_to_str(key_val))
            val_str = unquote(self.translate_value_to_str(rr_val_name))
            var_str = unquote(self.translate_value_to_str(rr_var_name)).strip("%")
            result.append(
                SetStmt(
                    variable=var_str,
                    value=LiteralValue(text=f"%%%{key_str},{val_str}%%%"),
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-09-READ",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Set {var_str}=%%%{key_str},{val_str}%%%",
                    doc_ref="Registry-DelayedRead",
                )
            )
            return result

        # MsgBoxEx / MsgBox -> Prompt
        if kind_lower in ("msgboxex", "msgbox"):
            msg_val = cmd.params.get("message") or (
                cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            )
            msg_str = unquote(self.translate_value_to_str(msg_val))
            msg_clean = msg_str.replace("<cr>", " ").replace("<CR>", " ").strip()
            result.append(
                Command(
                    name="Prompt",
                    args=[LiteralValue(text=f'"{msg_clean}"')],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-PROMPT",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"Prompt '{msg_clean[:40]}...'",
                    doc_ref="Benutzerdialoge",
                )
            )
            return result

        # System_Reset -> Exit 3010 (Reboot)
        if kind_lower.startswith("system_reset"):
            result.append(
                Comment(
                    text="; Rem Info: System_Reset (Neustart nach Installation angefordert)",
                    style="rem",
                )
            )
            result.append(
                Command(
                    name="Exit",
                    args=[LiteralValue(text="3010")],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-REBOOT",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary="System_Reset -> Exit 3010 (Reboot)",
                    doc_ref="Neustart",
                )
            )
            return result

        # LocalUserCreate
        if kind_lower == "localusercreate":
            user_name = (
                unquote(self.translate_value_to_str(cmd.raw_args[0])) if cmd.raw_args else "User"
            )
            result.append(
                Comment(
                    text=f"; Rem Info: LocalUserCreate '{user_name}' (Lokaler Benutzer)",
                    style="rem",
                )
            )
            result.append(
                CallStmt(
                    name="CallHidden",
                    program="cmd.exe",
                    arguments=[LiteralValue(text=f'/c net user "{user_name}" /add')],
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-SEC-01",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"LocalUserCreate '{user_name}'",
                    doc_ref="Benutzerverwaltung",
                )
            )
            return result

        # LocalUserSetPassword / LocalUserSetFlags
        if kind_lower in ("localusersetpassword", "localusersetflags"):
            user_name = (
                unquote(self.translate_value_to_str(cmd.raw_args[0])) if cmd.raw_args else "User"
            )
            result.append(
                Comment(
                    text=f"; Rem Info: LocalUserSetPassword '{user_name}'",
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-SEC-02",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"LocalUserSetPassword '{user_name}'",
                    doc_ref="Benutzerverwaltung",
                )
            )
            return result

        # LocalGroupAddMembers
        if kind_lower == "localgroupaddmembers":
            grp_raw = (
                unquote(self.translate_value_to_str(cmd.raw_args[0]))
                if cmd.raw_args
                else "Administratoren"
            )
            grp_name = grp_raw.split("|")[0].strip()
            members = [unquote(self.translate_value_to_str(a)).strip() for a in cmd.raw_args[1:]]
            result.append(
                Comment(
                    text=(
                        f"; Rem Info: LocalGroupAddMembers '{grp_name}': "
                        f"{', '.join(members) if members else 'Standard'}"
                    ),
                    style="rem",
                )
            )
            for m in members:
                if m:
                    result.append(
                        CallStmt(
                            name="CallHidden",
                            program="cmd.exe",
                            arguments=[
                                LiteralValue(text=f'/c net localgroup "{grp_name}" "{m}" /add')
                            ],
                            uninstall_only=is_uninstall,
                        )
                    )
            traces.append(
                RuleTrace(
                    rule_id="M-SEC-03",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"LocalGroupAddMembers '{grp_name}'",
                    doc_ref="Gruppenverwaltung",
                )
            )
            return result

        # LocalGroupRemoveMembers
        if kind_lower == "localgroupremovemembers":
            grp_raw = (
                unquote(self.translate_value_to_str(cmd.raw_args[0]))
                if cmd.raw_args
                else "Administratoren"
            )
            grp_name = grp_raw.split("|")[0].strip()
            members = [unquote(self.translate_value_to_str(a)).strip() for a in cmd.raw_args[1:]]
            result.append(
                Comment(
                    text=(
                        f"; Rem Info: LocalGroupRemoveMembers '{grp_name}': "
                        f"{', '.join(members) if members else 'Standard'}"
                    ),
                    style="rem",
                )
            )
            for m in members:
                if m:
                    result.append(
                        CallStmt(
                            name="CallHidden",
                            program="cmd.exe",
                            arguments=[
                                LiteralValue(text=f'/c net localgroup "{grp_name}" "{m}" /delete')
                            ],
                            uninstall_only=is_uninstall,
                        )
                    )
            traces.append(
                RuleTrace(
                    rule_id="M-SEC-04",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"LocalGroupRemoveMembers '{grp_name}'",
                    doc_ref="Gruppenverwaltung",
                )
            )
            return result

        # ChangeRegSecurity
        if kind_lower == "changeregsecurity":
            reg_path = unquote(self.translate_value_to_str(cmd.raw_args[0])) if cmd.raw_args else ""
            result.append(
                Comment(
                    text=f"; Rem Info: ChangeRegSecurity '{reg_path}' (Berechtigungen angepasst)",
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-SEC-05",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"ChangeRegSecurity '{reg_path}'",
                    doc_ref="Registry-Berechtigungen",
                )
            )
            return result

        # ModifyOem / ModifyOemEx -> Textdatei bearbeiten
        if kind_lower in ("modifyoem", "modifyoemex"):
            target_file = (
                unquote(self.translate_value_to_str(cmd.raw_args[0])) if cmd.raw_args else ""
            )
            entries = [
                unquote(self.translate_value_to_str(a)).strip()
                for a in cmd.raw_args[1:]
                if unquote(self.translate_value_to_str(a)).strip()
            ]
            result.append(
                Comment(
                    text=f"; Rem Info: ModifyOemEx '{target_file}' ({len(entries)} Zeilen)",
                    style="rem",
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-OEM",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"ModifyOemEx '{target_file}'",
                    doc_ref="Textdateien",
                )
            )
            return result

        # EndInstallerSession -> Exit
        if kind_lower == "endinstallersession":
            result.append(
                Command(
                    name="Exit",
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-SESSION",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary="EndInstallerSession -> Exit",
                    doc_ref="Ablaufsteuerung",
                )
            )
            return result

        # MSIReInstallProduct -> msiexec /f
        if kind_lower == "msireinstallproduct":
            guid_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            guid_str = unquote(self.translate_value_to_str(guid_val))
            result.append(
                CallStmt(
                    name="CallHidden",
                    program="msiexec.exe",
                    arguments=[
                        LiteralValue(text="/f"),
                        LiteralValue(text=f'"{guid_str}"'),
                        LiteralValue(text="/qn"),
                    ],
                    uninstall_only=is_uninstall,
                )
            )
            result.append(
                IfStmt(
                    condition=Comparison(
                        left=VarRef(name="ErrorLevel"),
                        relation="==",
                        right=LiteralValue(text="3010"),
                    ),
                    then_target="RebootRequired",
                    uninstall_only=is_uninstall,
                )
            )
            result.append(
                IfStmt(
                    condition=Comparison(
                        left=VarRef(name="ErrorLevel"),
                        relation="!=",
                        right=LiteralValue(text="0"),
                    ),
                    then_target="AbortMSIInst",
                    uninstall_only=is_uninstall,
                )
            )
            traces.append(
                RuleTrace(
                    rule_id="M-MSI-REINST",
                    source_line=cmd.src.line,
                    source_raw=cmd.src.raw,
                    confidence="high",
                    target_summary=f"MSIReInstallProduct '{guid_str}'",
                    doc_ref="MSI-Befehle",
                )
            )
            return result

        # Klasse 1 (Geheimbefehle): RenDir / RenameDir / RenameFolder
        if kind_lower in ("rendir", "renamedir", "renamefolder"):
            src_val = cmd.raw_args[0] if len(cmd.raw_args) > 0 else IrLiteral(value="")
            tgt_val = cmd.raw_args[1] if len(cmd.raw_args) > 1 else IrLiteral(value="")
            src_str = self.translate_value_to_str(src_val)
            tgt_str = self.translate_value_to_str(tgt_val)
            if self.allow_undocumented:
                result.append(
                    Command(
                        name="RenDir",
                        args=[
                            self._quote_path_if_needed(src_str),
                            self._quote_path_if_needed(tgt_str),
                        ],
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-BIN-03",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="medium",
                        target_summary=f"RenDir {src_str} {tgt_str}",
                        doc_ref="Binary-Tabelle (undokumentiert / Klasse 1)",
                    )
                )
            else:
                result.append(
                    Comment(
                        text=(
                            "Rem Hinweis (Klasse 1): RenDir erfordert "
                            "--allow-undocumented. Fallback auf cmd.exe:"
                        ),
                        style="rem",
                    )
                )
                result.append(
                    CallStmt(
                        name="CallHidden",
                        program="cmd.exe",
                        arguments=[
                            "/c",
                            "ren",
                            self._quote_path_if_needed(src_str),
                            self._quote_path_if_needed(tgt_str),
                        ],
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-BIN-03-FALLBACK",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="medium",
                        target_summary=f"CallHidden cmd.exe /c ren {src_str} {tgt_str}",
                        doc_ref="Klasse 1 Fallback",
                    )
                )
            return result

        # Klasse 1 (Geheimbefehle): CollapseEnv
        if kind_lower == "collapseenv":
            var_val = cmd.raw_args[0] if cmd.raw_args else IrLiteral(value="")
            var_str = self.translate_value_to_str(var_val).strip("%")
            if self.allow_undocumented:
                result.append(
                    Command(
                        name="CollapseEnv",
                        args=[var_str],
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-BIN-01",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="medium",
                        target_summary=f"CollapseEnv {var_str}",
                        doc_ref="Binary-Tabelle (undokumentiert / Klasse 1)",
                    )
                )
            else:
                result.append(
                    Comment(
                        text=(
                            f"Rem TODO (Klasse 1): CollapseEnv {var_str} "
                            "(erfordert --allow-undocumented)"
                        ),
                        style="rem",
                    )
                )
                todos.append(
                    IrTodo(
                        raw=cmd.src.raw,
                        message=(
                            f"Befehl CollapseEnv '{var_str}' erfordert "
                            "Feature-Flag --allow-undocumented"
                        ),
                        src=cmd.src,
                        confidence=0.5,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-BIN-01-TODO",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="todo",
                        target_summary=f"TODO: CollapseEnv {var_str}",
                        doc_ref="Binary-Tabelle (undokumentiert / Klasse 1)",
                    )
                )
            return result

        # Klasse 1 (Geheimbefehle): Extract
        if kind_lower == "extract":
            if self.allow_undocumented:
                result.append(
                    Command(
                        name="Extract",
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-BIN-02",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="medium",
                        target_summary="Extract",
                        doc_ref="Binary-Tabelle (undokumentiert / Klasse 1)",
                    )
                )
            else:
                result.append(
                    Comment(
                        text="Rem TODO (Klasse 1): Extract (erfordert --allow-undocumented)",
                        style="rem",
                    )
                )
                todos.append(
                    IrTodo(
                        raw=cmd.src.raw,
                        message="Befehl Extract erfordert Feature-Flag --allow-undocumented",
                        src=cmd.src,
                        confidence=0.5,
                    )
                )
            return result

        # Klasse 1 (Geheimbefehle): BlockInput / LockInput
        if kind_lower in ("blockinput", "lockinput"):
            flag_val = "1"
            if cmd.raw_args:
                arg_str = self.translate_value_to_str(cmd.raw_args[0]).strip().lower()
                if arg_str in ("0", "off", "false"):
                    flag_val = "0"
            if self.allow_undocumented:
                result.append(
                    Command(
                        name="BlockInput",
                        args=[flag_val],
                        uninstall_only=is_uninstall,
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-BIN-04",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="medium",
                        target_summary=f"BlockInput {flag_val}",
                        doc_ref="Binary-Tabelle (undokumentiert / Klasse 1)",
                    )
                )
            else:
                result.append(
                    Comment(
                        text=(
                            f"; Rem Info: BlockInput {flag_val} (befehlsbasiert nur mit "
                            "--allow-undocumented, sonst via [Setup] BlockInput)"
                        ),
                        style="rem",
                    )
                )
                traces.append(
                    RuleTrace(
                        rule_id="M-BIN-04-NOTE",
                        source_line=cmd.src.line,
                        source_raw=cmd.src.raw,
                        confidence="high",
                        target_summary=f"BlockInput {flag_val} Hinweis",
                        doc_ref="[Setup] BlockInput",
                    )
                )
            return result

        # Unhandled / DSM Infrastructure / TODO
        rule_def = self.rules.get_command_rule(cmd.kind)
        conf: Confidence = rule_def.confidence if rule_def else "todo"
        doc_ref = rule_def.doc_ref if rule_def else "Ivanti DSM"
        desc = rule_def.description if rule_def else f"Unrecognized command {cmd.kind}"

        result.append(Comment(text=f"Rem TODO ({cmd.kind}): {cmd.src.raw}", style="rem"))
        todos.append(
            IrTodo(
                raw=cmd.src.raw,
                message=desc,
                src=cmd.src,
                confidence=0.0,
            )
        )
        traces.append(
            RuleTrace(
                rule_id=rule_def.id if rule_def else "TODO",
                source_line=cmd.src.line,
                source_raw=cmd.src.raw,
                confidence=conf,
                target_summary=f"TODO: {desc}",
                doc_ref=doc_ref,
            )
        )
        return result

    def _transform_registry_keys(
        self, reg_keys: list[IrRegKey], traces: list[RuleTrace] | None = None
    ) -> list[SectionLine]:
        """Convert parsed IrRegKey objects to Empirum RegEntry models."""
        reg_entries: list[SectionLine] = []

        for key in reg_keys:
            if key.is_delete:
                # Key deletion: -HKLM,"Key" (executed during Empirum uninstall)
                reg_entries.append(
                    RegEntry(
                        root=key.root,
                        key=key.path,
                        delete=True,
                    )
                )
                if traces is not None:
                    traces.append(
                        RuleTrace(
                            rule_id="M-09",
                            source_line=1,
                            source_raw=f"[-{key.root}\\{key.path}]",
                            confidence="high",
                            target_summary=(
                                f"NIR deletion -{key.root},{key.path} assigned to [Reg:Product] "
                                "(executed at uninstall)"
                            ),
                            doc_ref="[Reg:<Name>]",
                        )
                    )
                continue

            for val in key.values:
                if val.is_delete:
                    # Value deletion: -HKLM,"Key","Value" (executed during Empirum uninstall)
                    reg_entries.append(
                        RegEntry(
                            root=key.root,
                            key=key.path,
                            delete_value=val.name,
                            delete=True,
                        )
                    )
                    if traces is not None:
                        traces.append(
                            RuleTrace(
                                rule_id="M-09",
                                source_line=1,
                                source_raw=f"-{val.name}",
                                confidence="high",
                                target_summary=(
                                    f"NIR value deletion -{key.root},{key.path},{val.name} "
                                    "assigned to [Reg:Product] (executed at uninstall)"
                                ),
                                doc_ref="[Reg:<Name>]",
                            )
                        )
                    continue

                flag = "0x00000000"  # Default REG_SZ
                data_str: str = val.raw_data.strip('"')

                if val.val_type == "REG_DWORD":
                    flag = "0x00010001"
                    data_str = str(val.dword_int if val.dword_int is not None else 0)
                elif val.val_type == "REG_QWORD":
                    flag = "0x00040001"
                    data_str = val.raw_data
                elif val.val_type == "REG_BINARY":
                    flag = "0x00000001"
                    data_str = val.raw_data
                elif val.val_type == "REG_MULTI_SZ":
                    flag = "0x00010000"
                    data_str = val.raw_data
                elif val.val_type == "REG_EXPAND_SZ":
                    flag = "0x00020000"
                    data_str = val.raw_data

                if val.parsed_value:
                    data_str = self.translate_value_to_str(val.parsed_value)

                reg_entries.append(
                    RegEntry(
                        root=key.root,
                        key=key.path,
                        value_name=val.name if val.name else None,
                        type_flag=flag,
                        data=[LiteralValue(text=data_str)],
                    )
                )

        return reg_entries

    def _get_uninstall_synthesizer(self) -> UninstallSynthesizer:
        return UninstallSynthesizer(
            translate_str_func=self.translate_value_to_str,
            quote_func=self._quote_path_if_needed,
            collected_reg_entries=self._collected_reg_entries,
            package_root=getattr(self, "_package_root", None),
            media_files=getattr(self, "_media_files", None),
            msi_product_codes=getattr(self, "_msi_product_codes", None),
        )

    def _extract_install_commands(self, nodes: list[IrNode]) -> list[IrCommand]:
        """Recursively extract install IrCommands from IR nodes."""
        return self._get_uninstall_synthesizer().extract_install_commands(nodes)

    def _invert_single_command(
        self,
        cmd: IrCommand,
        traces: list[RuleTrace],
        todos: list[IrTodo],
    ) -> tuple[str, list[SectionLine]]:
        """Invert an install command for uninstall."""
        return self._get_uninstall_synthesizer().invert_single_command(cmd, traces, todos)

    def _synthesize_uninstall_commands(
        self,
        install_nodes: list[IrNode],
        traces: list[RuleTrace],
        todos: list[IrTodo],
    ) -> list[SectionLine]:
        """Synthesize an inverted uninstall section (Set:Deinstallation) from install commands."""
        return self._get_uninstall_synthesizer().synthesize(install_nodes, traces, todos)

    def transform_package(
        self,
        pkg: IrPackage,
        parsed_nirs: list[IrRegKey] | None = None,
        developer_name: str = "Matrix42",
        product_name: str | None = None,
        version: str | None = None,
        package_root: Path | None = None,
        allow_undocumented: bool | None = None,
    ) -> TransformResult:
        """Transform full DSM package into compliant Empirum Setup.inf AST document."""
        if allow_undocumented is not None:
            self.allow_undocumented = allow_undocumented
        # Reset per-package state so a RuleEngine instance can be reused safely
        # across multiple packages (leaked _has_uninst_section previously emitted
        # a dangling '#Set:Deinstallation, DELETE' reference in [Product]).
        self._section_counter = 0
        self._has_client_section = False
        self._has_uninst_section = False
        self._has_user_context = False
        self._package_root = package_root
        self._media_files = list(pkg.media_files)
        self._msi_product_codes = dict(pkg.msi_product_codes)
        dev_name = pkg.manufacturer or developer_name
        prod_name = pkg.name or product_name or "MigratedApp"
        ver_str = pkg.version or version or "1.0"

        traces: list[RuleTrace] = []
        todos: list[IrTodo] = list(pkg.todos)
        extra_sections: list[Section] = []
        self._collected_shell_entries = []
        self._collected_reg_entries = []

        # 1. Transform commands from main script:
        # Separate commands into install portion (Set:Product) and
        # uninstall portion (Set:Deinstallation)
        set_product_cmds: list[SectionLine] = []
        if pkg.main_script:
            install_nodes: list[IrNode] = []
            uninstall_nodes: list[IrNode] = []
            seen_begin_uninstall = False

            for node in pkg.main_script.commands:
                if isinstance(node, IrLabel) and node.name.lower() == "$beginuninstallscript":
                    seen_begin_uninstall = True
                    continue
                if seen_begin_uninstall:
                    uninstall_nodes.append(node)
                else:
                    install_nodes.append(node)

            # Route DSM /TU (This User) commands to the user part [Set:Client]
            # before the machine pass is transformed; they must never execute
            # in the machine context.
            install_nodes, user_ctx_cmds = self._extract_user_context_commands(install_nodes)
            if user_ctx_cmds:
                user_ctx_cmds_list: list[IrNode] = list(user_ctx_cmds)
                user_client_cmds = self._transform_command_list(
                    user_ctx_cmds_list,
                    extra_sections,
                    traces,
                    todos,
                    is_uninstall_section=False,
                    in_branch=True,
                )
                if user_client_cmds:
                    existing_client_sec = next(
                        (s for s in extra_sections if s.name == "Set:Client"), None
                    )
                    if existing_client_sec:
                        existing_client_sec.lines.extend(user_client_cmds)
                    else:
                        extra_sections.append(
                            Section(
                                name="Set:Client",
                                kind=SectionKind.WORK,
                                lines=user_client_cmds,
                            )
                        )
                    self._has_client_section = True
                traces.append(
                    RuleTrace(
                        rule_id="S-05",
                        source_line=user_ctx_cmds[0].src.line,
                        source_raw=user_ctx_cmds[0].src.raw,
                        confidence="high",
                        target_summary=(
                            f"Routed {len(user_ctx_cmds)} /TU user command(s) to "
                            "[Set:Client] (CLIENT, /AW)"
                        ),
                        doc_ref="CLIENT / MACHINE Flags and /AW",
                    )
                )

            # Install commands (Change 3: is_uninstall_section=False ensures no '-' prefix)
            set_product_cmds = self._transform_command_list(
                install_nodes, extra_sections, traces, todos, is_uninstall_section=False
            )

            # Uninstall commands (Change 3: routed to Set:Deinstallation
            # with is_uninstall_section=True)
            if uninstall_nodes:
                uninst_cmds = self._transform_command_list(
                    uninstall_nodes,
                    extra_sections,
                    traces,
                    todos,
                    is_uninstall_section=True,
                    in_branch=True,
                )
                if uninst_cmds:
                    # Reverse order: Empirum Deinstallation runs bottom-to-top,
                    # so we emit the transformed commands in reverse DSM order.
                    # Sub-sections jumped into via SectionRef are NOT reversed;
                    # they execute forwards when called.
                    uninst_cmds = list(reversed(uninst_cmds))
                    existing_uninst_sec = next(
                        (s for s in extra_sections if s.name == "Set:Deinstallation"), None
                    )
                    if existing_uninst_sec:
                        existing_uninst_sec.lines.extend(uninst_cmds)
                    else:
                        extra_sections.append(
                            Section(
                                name="Set:Deinstallation", kind=SectionKind.WORK, lines=uninst_cmds
                            )
                        )
                    self._has_uninst_section = True

            # Change 1: If no uninstall section was present in DSM, synthesize one
            # if meaningful uninstall entries can be generated by inverting install actions
            if not self._has_uninst_section:
                synth_uninst_cmds = self._synthesize_uninstall_commands(
                    install_nodes, traces, todos
                )
                if synth_uninst_cmds:
                    extra_sections.append(
                        Section(
                            name="Set:Deinstallation",
                            kind=SectionKind.WORK,
                            lines=synth_uninst_cmds,
                        )
                    )
                    self._has_uninst_section = True

        # 2. Build standard-compliant sections
        sections: list[Section] = []

        # Determine method (MSI or Unattend)
        is_msi = any(m.suffix.lower() in (".msi", ".msp") for m in self._media_files) or bool(
            self._msi_product_codes
        )
        method_str = "MSI" if is_msi else "Unattend"
        has_hkcu = any(
            re.root.upper() in ("HKCU", "HKEY_CURRENT_USER") for re in self._collected_reg_entries
        ) or (
            parsed_nirs is not None
            and any(k.root.upper() in ("HKCU", "HKEY_CURRENT_USER") for k in parsed_nirs)
        )
        needs_aw = self._has_client_section or self._has_user_context or has_hkcu
        cmd_opts = "/S2 /AW" if needs_aw else "/S2"
        if needs_aw and not self._has_client_section:
            traces.append(
                RuleTrace(
                    rule_id="S-05",
                    source_line=1,
                    source_raw="HKCU / User profile context detected",
                    confidence="high",
                    target_summary=(
                        "Added /AW to [SetupInfo] Command line options for user context (VAL-006)"
                    ),
                    doc_ref="CLIENT / MACHINE Flags and /AW",
                )
            )

        # [SetupInfo]
        setupinfo_lines: list[SectionLine] = [
            KeyValue(key="Author", value=""),
            KeyValue(key="CreationDate", value=""),
            KeyValue(key="InventoryID", value=""),
            KeyValue(key="Description", value=pkg.description or ""),
            KeyValue(key="Method", value=method_str),
            KeyValue(key="Tested on", value=""),
            KeyValue(key="Dependencies", value=""),
            KeyValue(key="Command line options", value=cmd_opts),
            KeyValue(key="Last Change", value=""),
            KeyValue(key="Build", value="0"),
            KeyValue(key="Dskptn", value="Setup.inf"),
        ]
        comments_val = "Converted by DSM2Empirum"
        if pkg.revision_comment:
            comments_val = f"{comments_val} ({pkg.revision_comment})"
        elif pkg.description:
            comments_val = f"{comments_val} - {pkg.description}"
        setupinfo_lines.append(KeyValue(key="Comments", value=comments_val))

        sections.append(
            Section(
                name="SetupInfo",
                kind=SectionKind.META,
                lines=setupinfo_lines,
            )
        )

        # [VarDefInfo]
        sections.append(
            Section(
                name="VarDefInfo",
                kind=SectionKind.META,
                lines=[
                    Comment(
                        text=(
                            "<Variable>, <Type: 0=Computer 1=User>, <Allow NULL values: 0=No 1=Yes>"
                        )
                    ),
                ],
            )
        )

        # [Setup]
        sections.append(
            Section(
                name="Setup",
                kind=SectionKind.META,
                lines=[
                    KeyValue(key="Version", value="14.2"),
                    KeyValue(key="ShowCaption", value="1"),
                    KeyValue(key="BlockInput", value="0"),
                    KeyValue(key="Platform", value="*"),
                ],
            )
        )

        # [Requirements]
        sections.append(Section(name="Requirements", kind=SectionKind.META, lines=[]))

        # [Application]
        # Generate short names (max 8 chars, no spaces, uppercase)
        prod_name_short = prod_name.replace(" ", "")[:8].upper() or "APP"
        dev_name_short = dev_name.replace(" ", "")[:8].upper() or "DEV"

        app_entries: list[SectionLine] = [
            KeyValue(key="ProductName", value=prod_name),
            KeyValue(key="ProductNameShort", value=prod_name_short),
            KeyValue(key="DeveloperName", value=dev_name),
            KeyValue(key="DeveloperNameShort", value=dev_name_short),
            KeyValue(key="Version", value=ver_str),
            KeyValue(key="Revision", value=pkg.revision or "0"),
        ]
        if pkg.description:
            app_entries.append(KeyValue(key="Description", value=pkg.description))
        app_entries.extend(
            [
                KeyValue(key="SetupName", value="%ProductName% %Version% %SetupWizard%"),
                KeyValue(
                    key="Text1",
                    value=(
                        '"%ProductName% %Version%",         Arial,           30, , '
                        "2170F3, 4,    , LEFT BOLD ITALIC"
                    ),
                ),
                KeyValue(
                    key="Text2",
                    value=(
                        '"%DeveloperName%",                 Arial,           24, , '
                        "2170F3, 4,    , LEFT BOLD ITALIC"
                    ),
                ),
                KeyValue(
                    key="Text8",
                    value=(
                        '"%Company%",                       Arial,           18, , '
                        "2170F3, 4,  10, RIGHT BOLD ITALIC"
                    ),
                ),
                KeyValue(
                    key="Text9",
                    value=(
                        '"%InstallationFor% %WindowsUser%", Arial,           16, , '
                        "2170F3, 4, -18, BOTTOM ITALIC LEFT"
                    ),
                ),
                KeyValue(key="BackgroundColor", value="EFEFEF,000000"),
                KeyValue(key="CopyDialogRect", value="0%, 0%, 100%, 100%, HCENTER VCENTER"),
                KeyValue(
                    key="UserKeyName",
                    value=r"$Matrix42Packages$\%DeveloperName%\%ProductName%",
                ),
                KeyValue(
                    key="MachineKeyName",
                    value=r"$Matrix42Packages$\%DeveloperName%\%ProductName%\%Version%",
                ),
                KeyValue(
                    key="UninstallKeyName",
                    value=r"Matrix42 - %DeveloperName% %ProductName% %Version%",
                ),
                KeyValue(
                    key="UninstallDisplayName",
                    value=r"Matrix42 - %DeveloperName% %ProductName% %Version%",
                ),
                KeyValue(
                    key="UninstallString",
                    value=r"%ReinstallString% /U",
                ),
                KeyValue(
                    key="ReinstallString",
                    value=r'"%CommonSetupDir%\Setup.exe" "%App%\%SetupInfDir%\Setup.inf"',
                ),
                KeyValue(
                    key="UninstallDisplayIcon",
                    value=r'"%ApplicationDir%\%SetupInfDir%\Setup.ico",0',
                ),
                KeyValue(key="UninstallOptions", value="NOMODIFY SYSTEMCOMPONENT"),
                KeyValue(key="HideUninstall", value="1"),
                KeyValue(key="ReinstallMode", value="1"),
                KeyValue(key="SrcDir", value=".."),
                KeyValue(
                    key="ApplicationDir",
                    value=r"%CommonAppData%\$Matrix42Scripts$\%DeveloperName%\%ProductName%\%Version%",
                ),
                KeyValue(key="SetupInfDir", value="Install"),
                KeyValue(key="DataDir", value="%Personal%"),
                KeyValue(key="AskUninstallOld", value="1"),
                KeyValue(key="ShellLinks", value="1"),
                KeyValue(key="CommonShellLinks", value="1"),
                KeyValue(key="CreateUnresolvableShellLinks", value="1"),
                KeyValue(key="UseStringSection", value="Strings:09"),
                KeyValue(key="UseSysStringSection", value="SysStrings:09"),
                KeyValue(key="DateWarning", value="1"),
                KeyValue(key="SizeWarning", value="0"),
                KeyValue(key="Reboot", value="0"),
                KeyValue(key="PreventExternalReboot", value="1"),
                KeyValue(key="StartServicesOnReboot", value="0"),
                KeyValue(key="CallTimeOut", value="1800"),
                KeyValue(key="AbortAfterCallTimeOut", value="1"),
                KeyValue(key="DisableCancelButton", value="1"),
                KeyValue(key="ShowEndMessage", value="1"),
                KeyValue(key="EndMessage", value="%EndMessageDesc%"),
            ]
        )
        sections.append(Section(name="Application", kind=SectionKind.META, lines=app_entries))

        prod_desc = pkg.description or prod_name

        # [Strings:07]
        sections.append(
            Section(
                name="Strings:07",
                kind=SectionKind.META,
                lines=[
                    KeyValue(key="Disk1", value="Installationsmedium 1"),
                    KeyValue(
                        key="EndMessageDesc",
                        value="Die Installation wurde erfolgreich abgeschlossen!",
                    ),
                    KeyValue(
                        key="ErrorLogMessage",
                        value=(
                            "Die Installation/Deinstallation wurde mit einer Fehlermeldung"
                            " abgebrochen!"
                        ),
                    ),
                    KeyValue(key="InstallationFor", value="Installation für:"),
                    KeyValue(
                        key="InstallerDesc",
                        value="Dienstprogramm zum Installieren einzelner Komponenten.",
                    ),
                    KeyValue(key="InstallerName", value="Installationsprogramm"),
                    KeyValue(key="SetupWizard", value="Installations-Assistent"),
                    KeyValue(key="Uninstallation", value="deinstallieren"),
                    KeyValue(key="ErrorText", value="Fehler"),
                    KeyValue(key="CallingText", value="beim Aufruf von"),
                    KeyValue(key="ProductDesc", value=prod_desc),
                ],
            )
        )

        # [Strings:09]
        sections.append(
            Section(
                name="Strings:09",
                kind=SectionKind.META,
                lines=[
                    KeyValue(key="Disk1", value="Installation media 1"),
                    KeyValue(
                        key="EndMessageDesc",
                        value="Installation was completed successfully!",
                    ),
                    KeyValue(
                        key="ErrorLogMessage",
                        value=("The installation/uninstallation aborted with an error message!"),
                    ),
                    KeyValue(key="InstallationFor", value="Installation for:"),
                    KeyValue(
                        key="InstallerDesc",
                        value="Service program to install single components.",
                    ),
                    KeyValue(key="InstallerName", value="Setup program"),
                    KeyValue(key="SetupWizard", value="Installation Wizard"),
                    KeyValue(key="Uninstallation", value="Uninstallation"),
                    KeyValue(key="ErrorText", value="Error"),
                    KeyValue(key="CallingText", value="launching"),
                    KeyValue(key="ProductDesc", value=prod_desc),
                ],
            )
        )

        # [SysStrings:07]
        sections.append(
            Section(
                name="SysStrings:07",
                kind=SectionKind.META,
                lines=[
                    KeyValue(key="Users", value="Benutzer"),
                ],
            )
        )

        # [SysStrings:09]
        sections.append(
            Section(
                name="SysStrings:09",
                kind=SectionKind.META,
                lines=[
                    KeyValue(key="Users", value="Users"),
                ],
            )
        )

        # [Environment]
        sections.append(
            Section(
                name="Environment",
                kind=SectionKind.META,
                lines=[
                    KeyValue(
                        key="V_LogFileInstall",
                        value=r"%Temp%\Install_%ProductName%.%Version%.%Revision%.log",
                    ),
                    KeyValue(
                        key="V_LogFileUninstall",
                        value=r"%Temp%\Uninstall_%ProductName%.%Version%.%Revision%.log",
                    ),
                    KeyValue(
                        key="CommonSetupDir",
                        value=r"%CommonFilesDir%\Setup%SetupBits%",
                    ),
                    KeyValue(
                        key="V_MachineValuesPath",
                        value=r"\\%EmpirumServer%\Values$\MachineValues\%DomainName%",
                    ),
                    KeyValue(
                        key="V_UserValuesPath",
                        value=(
                            r'%HKLM,"Software\matrix42\Software Depot","HomeServer"%'
                            r"\Values$\UserValues\%UserDomain%"
                        ),
                    ),
                    KeyValue(
                        key="V_DisplayName",
                        value=f"{prod_name}*",
                    ),
                ],
            )
        )

        # [Encryption]
        sections.append(
            Section(
                name="Encryption",
                kind=SectionKind.META,
                lines=[],
            )
        )

        # [Disks]
        sections.append(
            Section(
                name="Disks",
                kind=SectionKind.META,
                lines=[
                    KeyValue(key="1", value="%Disk1%"),
                ],
            )
        )

        # [Options] (standard section from package template)
        sections.append(
            Section(
                name="Options",
                kind=SectionKind.OPTIONS,
                lines=[
                    KeyValue(
                        key="Installer",
                        value='%InstallerName%, COPYALWAYS, Installer, "%InstallerDesc%"',
                    ),
                    KeyValue(
                        key="Product",
                        value='%ProductName%,   COPYALWAYS, Product,   "%ProductDesc%"',
                    ),
                ],
            )
        )

        # [Processes]
        sections.append(
            Section(
                name="Processes",
                kind=SectionKind.META,
                lines=[],
            )
        )

        # [Installer] (Setup runtime files from package template)
        installer_lines: list[SectionLine] = [
            CopyEntry(
                disk=1,
                source=r"..\..\..\..\User\Setup.exe",
                destination="%CommonSetupDir%",
                flags=["OPTIONAL", "USEFILENAME", "DIRECTORY", "NOSIZEWARNING", "SETUP"],
                size=0,
            ),
            CopyEntry(
                disk=1,
                source=r"..\..\..\..\User\SetupDeu.chm",
                destination="%CommonSetupDir%",
                flags=["OPTIONAL", "USEFILENAME", "DIRECTORY", "NOSIZEWARNING", "SETUP"],
                size=0,
            ),
            CopyEntry(
                disk=1,
                source=r"..\..\..\..\User\SetupEnu.chm",
                destination="%CommonSetupDir%",
                flags=["OPTIONAL", "USEFILENAME", "DIRECTORY", "NOSIZEWARNING", "SETUP"],
                size=0,
            ),
            CopyEntry(
                disk=1,
                source=r"%Temp%\Setup64.exe",
                destination=r"%CommonSetupDir%\Setup.exe",
                flags=["OPTIONAL", "ALWAYS", "NOSIZEWARNING", "SETUP", "WINDOWS64"],
                size=0,
            ),
            CopyEntry(
                disk=1,
                source=r"..\..\..\..\User\Setup64.exe",
                destination=r"%CommonSetupDir%\Setup.exe",
                flags=["OPTIONAL", "ALWAYS", "NOSIZEWARNING", "SETUP", "WINDOWS64"],
                size=0,
            ),
            CopyEntry(
                disk=1,
                source=r"%SetupInfDir%\Setup.inf",
                destination="",
                flags=["ALWAYS"],
                size=0,
            ),
            CopyEntry(
                disk=1,
                source=r"%SetupInfDir%\Setup.ico",
                destination="",
                flags=["OPTIONAL"],
                size=0,
            ),
        ]
        sections.append(
            Section(
                name="Installer",
                kind=SectionKind.SUPPORT,
                lines=installer_lines,
            )
        )

        # [Product]
        # With a real user part present ([Set:Client] from imUserPart or /TU),
        # every machine-based entry gets the MACHINE flag so Setup.exe knows
        # exactly which parts run per machine and which per user (CLIENT).
        # Packages whose /AW comes only from HKCU/user-profile detection keep
        # their entries unflagged: that content deliberately runs in the user
        # pass as well (VAL-006 semantics).
        user_part_machine = ["MACHINE"] if self._has_client_section else []
        product_entries: list[SectionLine] = [
            Comment(text="Main Product Execution Section"),
            SectionRef(target="Set:Product", flags=["DONTDELETE", *user_part_machine]),
        ]

        if self._has_uninst_section:
            product_entries.append(
                SectionRef(target="Set:Deinstallation", flags=["DELETE", *user_part_machine])
            )

        all_reg_entries: list[SectionLine] = []
        if parsed_nirs:
            all_reg_entries.extend(self._transform_registry_keys(parsed_nirs, traces=traces))
        if self._collected_reg_entries:
            all_reg_entries.extend(self._collected_reg_entries)

        if all_reg_entries:
            # HKCU entries must also apply in the user pass, so [Reg:Product]
            # stays unflagged when mixed user/machine registry data exists.
            reg_machine = [] if has_hkcu else user_part_machine
            product_entries.append(SectionRef(target="Reg:Product", flags=reg_machine))

        # Note: ShellLinks = 1 in [Application] causes Setup.exe to execute [Shell:Product]
        # automatically at the end of installation. Explicitly referencing #Shell:Product here
        # would execute shortcuts twice (Empirum anti-pattern 9), so it is omitted here.
        # if self._collected_shell_entries:
        #     product_entries.append(SectionRef(target="Shell:Product"))

        if self._has_client_section:
            product_entries.append(SectionRef(target="Set:Client", flags=["CLIENT"]))

        sections.append(Section(name="Product", kind=SectionKind.WORK, lines=product_entries))

        # [Set:Product]
        sections.append(Section(name="Set:Product", kind=SectionKind.WORK, lines=set_product_cmds))

        # Any extra sections generated by If/Else blocks
        sections.extend(extra_sections)

        # [Reg:Product] (if registry data exists)
        if all_reg_entries:
            sections.append(
                Section(
                    name="Reg:Product",
                    kind=SectionKind.TYPED,
                    typed_prefix="Reg",
                    lines=all_reg_entries,
                )
            )

        # [Shell:Product] (if shortcuts exist)
        if self._collected_shell_entries:
            sections.append(
                Section(
                    name="Shell:Product",
                    kind=SectionKind.TYPED,
                    typed_prefix="Shell",
                    lines=list(self._collected_shell_entries),
                )
            )

        # [RebootRequired] (standard reboot section)
        sections.append(
            Section(
                name="RebootRequired",
                kind=SectionKind.WORK,
                lines=[
                    SetRebootStmt(mode=0),
                    SetRebootStmt(mode=0, uninstall_only=True),
                ],
            )
        )

        # [AbortMSIInst] (Standard Error section - both install and uninstall lines
        # so that Setup.exe executes them in normal and /U reverse mode).
        # Only emitted for packages that actually perform MSI operations: the
        # section ships only when a transformed command jumps to it (msiexec
        # calls / MSI product commands), so pure unattend packages stay clean.
        abort_msi_referenced = any(
            isinstance(line, IfStmt)
            and (
                line.then_target.strip().lower() == "abortmsiinst"
                or (line.else_target or "").strip().lower() == "abortmsiinst"
            )
            for sec in sections
            for line in sec.lines
        )
        if abort_msi_referenced:
            sections.append(
                Section(
                    name="AbortMSIInst",
                    kind=SectionKind.WORK,
                    lines=[
                        Command(name="ErrorLogMsg", args=[VarRef(name="ErrorText")]),
                        Command(
                            name="Abort",
                            args=[LiteralValue(text="Installation terminated with error")],
                        ),
                        Command(
                            name="ErrorLogMsg",
                            args=[VarRef(name="ErrorText")],
                            uninstall_only=True,
                        ),
                        Command(
                            name="Abort",
                            args=[LiteralValue(text="Installation terminated with error")],
                            uninstall_only=True,
                        ),
                    ],
                )
            )

        # [Set:InstallationError], [Set:ReinstallationError], [Set:DeInstallationError]
        # (standard error sections)
        sections.extend(
            [
                Section(
                    name="Set:InstallationError",
                    kind=SectionKind.WORK,
                    lines=[
                        Command(name="ErrorLogMsg", args=[VarRef(name="ErrorLogMessage")]),
                        Command(name="Abort", args=[]),
                    ],
                ),
                Section(
                    name="Set:ReinstallationError",
                    kind=SectionKind.WORK,
                    lines=[
                        Command(name="ErrorLogMsg", args=[VarRef(name="ErrorLogMessage")]),
                        Command(name="Abort", args=[]),
                    ],
                ),
                Section(
                    name="Set:DeInstallationError",
                    kind=SectionKind.WORK,
                    lines=[
                        Command(
                            name="ErrorLogMsg",
                            args=[VarRef(name="ErrorLogMessage")],
                            uninstall_only=True,
                        ),
                        Command(name="Abort", args=[], uninstall_only=True),
                    ],
                ),
            ]
        )

        # Ensure all referenced section targets exist as sections (prevent E1007)
        existing_sec_names = {s.name.strip().lower() for s in sections}
        missing_stubs: list[Section] = []
        for s in sections:
            for line in s.lines:
                targets_to_check: list[str] = []
                if isinstance(line, SectionRef):
                    targets_to_check.append(line.target)
                elif isinstance(line, IfStmt):
                    if line.then_target:
                        targets_to_check.append(line.then_target)
                    if line.else_target:
                        targets_to_check.append(line.else_target)
                for tgt in targets_to_check:
                    clean_tgt = tgt.strip().strip('"').strip("'")
                    if clean_tgt and clean_tgt.lower() not in existing_sec_names:
                        existing_sec_names.add(clean_tgt.lower())
                        missing_stubs.append(
                            Section(
                                name=clean_tgt,
                                kind=SectionKind.WORK,
                                lines=[
                                    Comment(
                                        text=f"Autogenerated stub section for target '{clean_tgt}'"
                                    )
                                ],
                            )
                        )
        sections.extend(missing_stubs)

        doc = InfDocument(sections=sections)

        # Calculate average confidence via the shared Chapter 5.4 implementation
        # (same formula as report/kpi.py and tools/collect_stats.py)
        counts = count_constructs(traces, todos)
        avg_conf = weighted_average_confidence(
            counts["high"], counts["medium"], counts["low"], counts["todo"]
        )

        return TransformResult(
            document=doc,
            traces=traces,
            todos=todos,
            average_confidence=round(avg_conf, 2),
        )
