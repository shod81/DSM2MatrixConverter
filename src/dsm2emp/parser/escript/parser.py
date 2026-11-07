"""eScript parser with indentation tracking and AST/IR builder."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dsm2emp.parser.escript.conditions import parse_condition_expr
from dsm2emp.parser.escript.lexer import (
    extract_command_parts,
    parse_dsm_value,
    unquote,
)
from dsm2emp.parser.ir import (
    IrCommand,
    IrComment,
    IrCondition,
    IrGoto,
    IrIf,
    IrLabel,
    IrLiteral,
    IrNode,
    IrScript,
    IrTodo,
    IrValue,
    SourceRef,
)


@dataclass
class _IfFrame:
    """Tracking frame for nested If/Else blocks."""

    indent: int
    conditions: list[IrCondition]
    src: SourceRef
    condition_op: Literal["|", "&"] = "|"
    is_mixed: bool = False
    then_body: list[IrNode] = field(default_factory=list)
    else_body: list[IrNode] = field(default_factory=list)
    in_else: bool = False

    def add_node(self, node: IrNode) -> None:
        if self.in_else:
            self.else_body.append(node)
        else:
            self.then_body.append(node)

    @property
    def last_node(self) -> IrNode | None:
        if self.in_else:
            return self.else_body[-1] if self.else_body else None
        return self.then_body[-1] if self.then_body else None

    def to_ir_if(self) -> IrIf:
        return IrIf(
            conditions=self.conditions,
            condition_op=self.condition_op,
            is_mixed=self.is_mixed,
            then_body=self.then_body,
            else_body=self.else_body,
            src=self.src,
        )


def _get_line_indent(line: str) -> int:
    """Calculate leading whitespace indentation level (tabs count as 4 spaces)."""
    count = 0
    for char in line:
        if char == " ":
            count += 1
        elif char == "\t":
            count += 4
        else:
            break
    return count


def _map_command_params(cmd_name: str, args: list[IrValue]) -> dict[str, IrValue]:
    """Map positional command arguments to named parameters for known DSM commands."""
    params: dict[str, IrValue] = {}
    cmd_lower = cmd_name.lower()

    if cmd_lower == "set" and len(args) >= 2:
        params["name"] = args[0]
        params["value"] = args[1]
    elif cmd_lower in ("executeex", "execute") and len(args) >= 1:
        params["command"] = args[0]
        if len(args) >= 2:
            params["rc_var"] = args[1]
        if len(args) >= 3:
            params["expected_rc"] = args[2]
    elif cmd_lower == "copy" and len(args) >= 2:
        params["source"] = args[0]
        params["destination"] = args[1]
        if len(args) >= 3:
            params["flags"] = args[2]
    elif (
        cmd_lower
        in (
            "installfile",
            "delete",
            "makedir",
            "createfolder",
            "removedir",
            "removefolder",
            "regload",
            "regloadex",
            "changentfssecurity",
            "changeregsecurity",
        )
        and args
    ):
        params["path"] = args[0]
    elif cmd_lower in ("startservice", "stopservice", "uninstallservice") and args:
        params["service_name"] = args[0]
    elif cmd_lower == "installservice" and args:
        params["service_file"] = args[0]
        if len(args) >= 2:
            params["service_name"] = args[1]
        if len(args) >= 3:
            params["command"] = args[2]
    elif cmd_lower in ("regreadvalue", "regreadvalueex", "regread") and args:
        params["key"] = args[0]
        if len(args) >= 2:
            params["value_name"] = args[1]
        if len(args) >= 3:
            params["var_name"] = args[2]
    elif cmd_lower == "createinternetlink" and args:
        params["link_name"] = args[0]
        if len(args) >= 2:
            params["url"] = args[1]
    elif cmd_lower in ("msgboxex", "msgbox") and args:
        params["message"] = args[0]
        if len(args) >= 2:
            params["title"] = args[1]
    elif cmd_lower in ("localusercreate", "localusersetpassword", "localusersetflags") and args:
        params["user_name"] = args[0]
        if len(args) >= 2:
            params["full_name_or_pwd"] = args[1]
    elif cmd_lower in ("localgroupaddmembers", "localgroupremovemembers") and args:
        params["group_name"] = args[0]
    elif cmd_lower in ("createlink", "removelink") and len(args) >= 1:
        params["link_name"] = args[0]
        if len(args) >= 2:
            params["target_path"] = args[1]
        if len(args) >= 3:
            params["arguments"] = args[2]
        if len(args) >= 4:
            params["working_dir"] = args[3]
    elif cmd_lower == "msiinstallproduct" and args:
        params["msi_path"] = args[0]
        if len(args) >= 2:
            params["flags"] = args[1]
    elif cmd_lower == "msiuninstallproduct" and args:
        params["guid"] = args[0]
        if len(args) >= 2:
            params["name"] = args[1]
    elif (
        cmd_lower
        in (
            "regdeletekey",
            "regdeletevalue",
            "regmodify",
            "regmodifydword",
            "regmodifyqword",
            "regmodifymultisz",
        )
        and args
    ):
        params["key"] = args[0]
        if len(args) >= 2:
            params["value_name"] = args[1]
        if len(args) >= 3:
            params["data"] = args[2]
        if len(args) >= 4:
            params["flags"] = args[3]
    elif cmd_lower == "msiapplypatch" and args:
        params["patch"] = args[0]
    elif cmd_lower in ("callscript", "callscriptas") and args:
        params["script"] = args[0]
        if len(args) >= 2:
            params["arguments"] = args[1]
        if len(args) >= 3:
            params["user"] = args[2]
        if len(args) >= 4:
            params["password"] = args[3]
        if len(args) >= 5:
            params["flags"] = args[4]
    elif cmd_lower == "uninstallservice" and args:
        params["service_name"] = args[0]
    elif cmd_lower in ("exitproc", "exitprocex") and args:
        params["status"] = args[0]
        if len(args) >= 2:
            params["message"] = args[1]
    elif cmd_lower == "sleep" and args:
        params["seconds"] = args[0]
    elif cmd_lower == "killprocess" and args:
        params["process_name"] = args[0]

    return params


def parse_script(text: str, file_path: Path) -> IrScript:
    """Parse raw DSM eScript text into an IrScript AST with typed commands."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    root_commands: list[IrNode] = []
    if_stack: list[_IfFrame] = []
    phase: Literal["install", "uninstall", "both"] = "install"

    def append_node(node: IrNode) -> None:
        if if_stack:
            if_stack[-1].add_node(node)
        else:
            root_commands.append(node)

    def close_if() -> None:
        if if_stack:
            top = if_stack.pop()
            ir_if = top.to_ir_if()
            append_node(ir_if)

    for line_idx, raw_line in enumerate(lines, 1):
        stripped = raw_line.strip()
        if not stripped:
            continue

        indent = _get_line_indent(raw_line)
        src = SourceRef(file=file_path, line=line_idx, col=indent + 1, raw=raw_line)

        # 2. Comments (; //, Rem, or !)
        is_comment = (
            stripped.startswith(";")
            or stripped.startswith("//")
            or stripped.lower().startswith("rem ")
            or stripped.startswith("!")
        )
        if is_comment:
            append_node(IrComment(text=stripped, src=src))
            continue

        # 3. Label definition (:Label or Label(:Label))
        if stripped.startswith(":"):
            label_name = stripped[1:].strip()
            if label_name.lower() == "$beginuninstallscript":
                while if_stack:
                    close_if()
                phase = "uninstall"
                append_node(IrLabel(name="$BeginUninstallScript", src=src))
                continue
            append_node(IrLabel(name=label_name, src=src))
            continue
        if stripped.lower().startswith("label(") and stripped.endswith(")"):
            inner = stripped[6:-1].strip().lstrip(":")
            if inner.lower() == "$beginuninstallscript":
                while if_stack:
                    close_if()
                phase = "uninstall"
                append_node(IrLabel(name="$BeginUninstallScript", src=src))
                continue
            append_node(IrLabel(name=unquote(inner), src=src))
            continue

        # 4. Phase switch: $BeginUnInstallScript
        if stripped.lower() == "$beginuninstallscript":
            while if_stack:
                close_if()
            phase = "uninstall"
            append_node(IrLabel(name="$BeginUninstallScript", src=src))
            continue

        # 5. GOTO
        if stripped.lower().startswith("goto"):
            parts = stripped.split(maxsplit=1)
            target = parts[1].strip().lstrip(":") if len(parts) > 1 else ""
            append_node(IrGoto(target=target, src=src))
            continue

        # 6. If / Else / EndIf
        stripped_lower = stripped.lower()
        if stripped_lower.startswith("if ") or stripped_lower.startswith("if("):
            cond_str = (
                stripped[2:].strip() if stripped_lower.startswith("if(") else stripped[3:].strip()
            )
            # If the entire condition is wrapped in outer parens, e.g. If (A == B)
            if cond_str.startswith("(") and cond_str.endswith(")"):
                depth = 0
                is_outer = True
                for i, ch in enumerate(cond_str):
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0 and i < len(cond_str) - 1:
                            is_outer = False
                            break
                if is_outer:
                    cond_str = cond_str[1:-1].strip()
            conditions, cond_op, is_mixed = parse_condition_expr(cond_str)
            if is_mixed:
                append_node(
                    IrTodo(
                        raw=raw_line,
                        message="Mixed AND/OR condition in If statement requires manual review",
                        src=src,
                    )
                )
            if_stack.append(
                _IfFrame(
                    indent=indent,
                    conditions=conditions,
                    src=src,
                    condition_op=cond_op,
                    is_mixed=is_mixed,
                )
            )
            continue

        if stripped.lower() == "else":
            # Close any unclosed inner Ifs that were deeper than this Else
            while if_stack and indent < if_stack[-1].indent:
                close_if()
            if if_stack:
                if_stack[-1].in_else = True
            else:
                append_node(IrTodo(raw=raw_line, message="Dangling Else without If", src=src))
            continue

        if stripped.lower() in ("endif", "end if"):
            # Close any unclosed inner Ifs deeper than this EndIf
            while if_stack and indent < if_stack[-1].indent:
                close_if()
            if if_stack:
                close_if()
            else:
                append_node(IrTodo(raw=raw_line, message="Dangling EndIf without If", src=src))
            continue

        # For normal commands: close any If where indentation dropped to <= If indent
        while if_stack and indent <= if_stack[-1].indent:
            close_if()

        def _get_active_last_node() -> IrNode | None:
            if if_stack:
                return if_stack[-1].last_node
            return root_commands[-1] if root_commands else None

        active_last_node = _get_active_last_node()

        # 6.5. params: continuation block for preceding command
        if stripped.lower().startswith("params:"):
            extra = stripped[7:].strip()
            if extra:
                if isinstance(active_last_node, IrCommand):
                    active_last_node.raw_args.append(parse_dsm_value(extra))
            continue

        # 6.6. MST transform continuation line (|.\path\to.mst;)
        if stripped.startswith("|") and ".mst" in stripped.lower():
            mst_clean = stripped.lstrip("|").rstrip(";").strip()
            if isinstance(active_last_node, IrCommand):
                active_last_node.raw_args.append(parse_dsm_value(f'TRANSFORMS="{mst_clean}"'))
            continue

        # 6.7. SID / ACL continuation line for ChangeNTFSSecurity / ChangeRegSecurity
        if stripped.upper().startswith("S-1-"):
            parts = stripped.split()
            sid = parts[0]
            perms = parts[1] if len(parts) > 1 else "DRWX"
            if isinstance(active_last_node, IrCommand) and active_last_node.kind.lower() in (
                "changentfssecurity",
                "changeregsecurity",
            ):
                active_last_node.raw_args.append(parse_dsm_value(sid))
                active_last_node.raw_args.append(parse_dsm_value(perms))
            continue

        # 6.8. File list item following InstallFileList, CopyFileList, or DeleteFileList
        is_path_like = (
            stripped.startswith(".\\")
            or stripped.startswith("./")
            or stripped.startswith("\\")
            or bool(re.match(r"^[a-zA-Z]:[\\/]", stripped))
            or (stripped.startswith("%") and ("\\" in stripped or "/" in stripped))
        )
        if is_path_like:
            if isinstance(active_last_node, IrCommand) and active_last_node.kind.lower() in (
                "installfilelist",
                "copyfilelist",
                "deletefilelist",
            ):
                active_last_node.raw_args.append(parse_dsm_value(stripped))
                continue
            append_node(IrComment(text=f"; Rem Deaktivierte Dateiliste: {stripped}", src=src))
            continue

        # 6.9. INI Section or Key-Value item following AddIni
        if isinstance(active_last_node, IrCommand) and active_last_node.kind.lower() == "addini":
            if (stripped.startswith("[") and stripped.endswith("]")) or "=" in stripped:
                if not any(
                    stripped.lower().startswith(kw)
                    for kw in (
                        "if ",
                        "if(",
                        "else",
                        "endif",
                        "end if",
                        "goto ",
                        "endproc",
                        "exitproc",
                        "copy",
                        "execute",
                    )
                ):
                    active_last_node.raw_args.append(parse_dsm_value(stripped))
                    continue

        # 6.10. File content items following ModifyOem / ModifyOemEx / AppendTextFile
        if isinstance(active_last_node, IrCommand) and active_last_node.kind.lower() in (
            "modifyoem",
            "modifyoemex",
            "appendtextfile",
            "replacetextfile",
        ):
            if indent > 0 and not any(
                stripped.lower().startswith(kw)
                for kw in (
                    "if ",
                    "if(",
                    "else",
                    "endif",
                    "end if",
                    "goto ",
                    "endproc",
                    "exitproc",
                    "copy",
                    "execute",
                )
            ):
                active_last_node.raw_args.append(parse_dsm_value(stripped))
                continue

        # 6.11. IP address line (HOSTS file entry under disabled ModifyOemEx)
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", stripped):
            append_node(IrComment(text=f"; Rem Deaktivierter HOSTS-Eintrag: {stripped}", src=src))
            continue

        # 6.12. Member items following LocalGroupAddMembers / LocalGroupRemoveMembers
        if isinstance(active_last_node, IrCommand) and active_last_node.kind.lower() in (
            "localgroupaddmembers",
            "localgroupremovemembers",
        ):
            if indent > 0 and not any(
                stripped.lower().startswith(kw)
                for kw in (
                    "if ",
                    "if(",
                    "else",
                    "endif",
                    "end if",
                    "goto ",
                    "endproc",
                    "exitproc",
                    "local",
                    "set",
                )
            ):
                active_last_node.raw_args.append(parse_dsm_value(stripped))
                continue

        # 7. Standard or Custom Commands
        try:
            cmd_name, raw_args, flags = extract_command_parts(stripped)
            if not cmd_name:
                continue

            parsed_args: list[IrValue] = []
            for arg_str in raw_args:
                parsed_args.append(parse_dsm_value(arg_str))

            # Check if any arg or flag is a /P (prevent uninstall) flag
            prevent_uninstall = "P" in flags
            x64_redirect_off = "X64" in flags
            continue_on_error = "C" in flags
            cmd_phase: Literal["install", "uninstall", "both"] = phase
            cmd_context: Literal["user", "machine", "service", "unknown"] = "machine"
            # /TU = "This User": command runs in the logged-on user's context
            # (DSM user part) - NOT an uninstall marker. Only the bare /U flag
            # marks an uninstall-only command.
            if "TU" in flags:
                cmd_context = "user"
            elif "U" in flags:
                cmd_phase = "uninstall"

            filtered_args: list[IrValue] = []
            for arg in parsed_args:
                if isinstance(arg, IrLiteral) and arg.value.upper() == "/P":
                    prevent_uninstall = True
                else:
                    filtered_args.append(arg)

            params = _map_command_params(cmd_name, filtered_args)

            cmd_node = IrCommand(
                kind=cmd_name,
                params=params,
                raw_args=filtered_args,
                phase=cmd_phase,
                context=cmd_context,
                x64_redirect_off=x64_redirect_off,
                continue_on_error=continue_on_error,
                prevent_uninstall=prevent_uninstall,
                src=src,
            )
            append_node(cmd_node)
        except Exception as ex:
            # Fallback gracefully to IrTodo on unexpected parsing issue
            append_node(
                IrTodo(
                    raw=raw_line,
                    message=f"Parser exception: {ex}",
                    src=src,
                    confidence=0.0,
                )
            )

    # Close any unclosed If frames at end of file
    while if_stack:
        close_if()

    return IrScript(file=file_path, commands=root_commands)
