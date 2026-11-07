"""Central quoting and escaping engine for Setup.inf generation.

According to architecture rules, this module is the SINGLE SOURCE OF TRUTH
for quoting decisions, comma handling, and character escaping.
"""

import re
from dataclasses import dataclass
from typing import Literal

from dsm2emp.ast.nodes import (
    CallStmt,
    Command,
    Comparison,
    Condition,
    CopyEntry,
    FunctionCall,
    GroupCondition,
    IfStmt,
    RegEntry,
    SectionRef,
    SetRebootStmt,
    SetStmt,
    ShellEntry,
)
from dsm2emp.ast.values import (
    IndirectVar,
    IniRef,
    LiteralValue,
    RegistryRef,
    Value,
    VarRef,
)


@dataclass(frozen=True)
class Issue:
    """Diagnostic issue produced during quoting or AST processing."""

    code: str  # e.g. "W2004", "E1004"
    message: str
    severity: Literal["info", "warning", "error"]
    field: str | None = None


def needs_quotes(text: str) -> bool:
    """Check if a text token requires double quotes.

    True if text contains space, tab, comma, semicolon, or starts/ends with whitespace.
    """
    if not text:
        return False
    if text.startswith('"') and text.endswith('"'):
        return False
    if text.startswith("'") and text.endswith("'"):
        return False
    return any(c in text for c in (" ", "\t", ",", ";")) or text != text.strip()


def validate_percent_count(text: str, issues: list[Issue] | None = None) -> bool:
    """Check that percent signs are balanced (F-24).

    Exempts Windows shell argument placeholders such as %1-%9, %*, %~1, etc.
    which commonly appear in Registry file association commands.
    """
    clean_text = re.sub(r"(?<!%)%(?:[0-9*]|~[A-Za-z0-9]+)(?!%)", "", text)
    count = clean_text.count("%")
    if count % 2 != 0:
        if issues is not None:
            issues.append(
                Issue(
                    code="E1005",
                    message=f"Odd number of percent signs in token: '{text}'",
                    severity="error",
                )
            )
        return False
    return True


def q_var(var: VarRef) -> str:
    """Format variable reference according to flags."""
    if var.short_name:
        return f"%~{var.name}%"
    if var.trailing_bs:
        return f"%{var.name}\\%"
    if var.leading_bs:
        return f"%\\{var.name}%"
    return f"%{var.name}%"


def q_value(val: Value | str, issues: list[Issue] | None = None, force_quote: bool = False) -> str:
    """Serialize a Value or string safely.

    Handles F-14 (semicolon), F-15 (embedded quotes warning), and standard comma/space quoting.
    """
    if isinstance(val, VarRef):
        return q_var(val)

    if isinstance(val, IndirectVar):
        if isinstance(val.inner, VarRef):
            inner_str = q_var(val.inner)
        elif isinstance(val.inner, LiteralValue):
            inner_str = f"%{val.inner.text}%"
        else:
            inner_str = f"%{val.inner}%"
        return f"%%{val.outer}{inner_str}%%"

    if isinstance(val, IniRef):
        return f"%{val.file},{val.section},{val.key}%"

    if isinstance(val, RegistryRef):
        if val.ms_syntax:
            v_part = f',"{val.value}"' if val.value is not None else ""
            return f'%{val.root},"{val.key}"{v_part}%'
        v_part = f",{val.value}" if val.value is not None else ""
        return f"%{val.root},{val.key}{v_part}%"

    raw_text = val.text if isinstance(val, LiteralValue) else str(val)

    # Check for embedded double quotes (F-15)
    if '"' in raw_text and not (raw_text.startswith('"') and raw_text.endswith('"')):
        if issues is not None:
            issues.append(
                Issue(
                    code="W2004",
                    message=f"Value contains unescapable double quotes: {raw_text}",
                    severity="warning",
                )
            )
        return raw_text

    # Already quoted?
    if raw_text.startswith('"') and raw_text.endswith('"'):
        return raw_text

    if force_quote or needs_quotes(raw_text):
        return f'"{raw_text}"'

    return raw_text


def q_key_value(val: Value | str, issues: list[Issue] | None = None) -> str:
    """Format the value of a KeyValue line in INI/metadata sections.

    In INI key-value assignments (e.g. DeveloperName=Optimal Systems, Disk1=Installationsmedium 1),
    values do NOT require outer quotes for spaces or commas (standard INI syntax).
    Outer quotes become part of the variable value in Empirum runtime,
    corrupting path expansions such as ApplicationDir.
    If the value already contains quotes (e.g. ReinstallString="%CommonSetupDir%\\Setup.exe" ...
    or Text1="%ProductName% %Version%", Arial, ...), those are preserved.
    """
    if isinstance(val, VarRef):
        return q_var(val)

    if isinstance(val, IndirectVar):
        if isinstance(val.inner, VarRef):
            inner_str = q_var(val.inner)
        elif isinstance(val.inner, LiteralValue):
            inner_str = f"%{val.inner.text}%"
        else:
            inner_str = f"%{val.inner}%"
        return f"%%{val.outer}{inner_str}%%"

    if isinstance(val, IniRef):
        return f"%{val.file},{val.section},{val.key}%"

    if isinstance(val, RegistryRef):
        if val.ms_syntax:
            v_part = f',"{val.value}"' if val.value is not None else ""
            return f'%{val.root},"{val.key}"{v_part}%'
        v_part = f",{val.value}" if val.value is not None else ""
        return f"%{val.root},{val.key}{v_part}%"

    raw_text = val.text if isinstance(val, LiteralValue) else str(val)
    validate_percent_count(raw_text, issues)
    return raw_text


def is_balanced_quotes(text: str) -> bool:
    """Check if all double quotes in text are properly paired and balanced."""
    if '"' not in text:
        return True
    if text.count('"') % 2 != 0:
        return False
    in_quotes = False
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
    return not in_quotes


def is_token_whitespace_quoted(text: str) -> bool:
    """Check if all whitespace characters in text are inside double quotes."""
    in_quotes = False
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch in (" ", "\t") and not in_quotes:
            return False
    return not in_quotes


def q_call_token(
    token: Value | str,
    issues: list[Issue] | None = None,
    is_program: bool = False,
) -> str:
    """Format a token in Call / CallHidden commands (F-02, F-03, F-08)."""
    token_str = token.text if isinstance(token, LiteralValue) else str(token)

    # For CLI parameter tokens with balanced quotes (e.g. PARAM="VALUE" or /I"VALUE" or "VALUE"),
    # do not flag W2004 since Windows/Empirum natively understands these parameter quotes.
    cli_issues = issues
    if not is_program and is_balanced_quotes(token_str) and token_str.count('"') >= 2:
        cli_issues = None

    raw_str = q_value(token, issues=cli_issues)
    if raw_str.startswith('"') and raw_str.endswith('"'):
        return raw_str

    # Auto-balance single unclosed quote on CLI argument tokens (e.g. -responseFile "path or -f1:"path)
    if not is_program and raw_str.count('"') % 2 != 0:
        if raw_str.startswith('"') and not raw_str.endswith('"'):
            raw_str = raw_str + '"'
        elif any(sep in raw_str for sep in ('="', ':"', ' "')) and not raw_str.endswith('"'):
            raw_str = raw_str + '"'
        elif not raw_str.startswith('"') and raw_str.endswith('"'):
            raw_str = '"' + raw_str
        else:
            raw_str = raw_str + '"' 

    # In Empirum, program path in Call is quoted when containing variables, slashes, or spaces
    if is_program:
        if any(c in raw_str for c in (" ", "\t", "\\", "/", "%")):
            return f'"{raw_str}"'
        return raw_str

    # F-08: Check if literal % needs doubling outside variables
    if "%" in raw_str and not (raw_str.startswith("%") and raw_str.endswith("%")):
        if raw_str.count("%") == 1:
            raw_str = raw_str.replace("%", "%%")

    if any(c in raw_str for c in (" ", "\t")):
        # Only wrap in outer quotes if the whitespace is not already quoted
        if not (is_balanced_quotes(raw_str) and is_token_whitespace_quoted(raw_str)):
            return f'"{raw_str}"'

    return raw_str


def q_reg_component(comp: str, issues: list[Issue] | None = None) -> str:
    """Format a registry path component (F-10, F-16)."""
    if "'" in comp and issues is not None:
        issues.append(
            Issue(
                code="E1004",
                message=f"Single quotes in registry component not supported: '{comp}'",
                severity="error",
            )
        )
    if "," in comp:
        return f"'{comp}'"
    return comp


def q_function_call(fn: FunctionCall, issues: list[Issue] | None = None) -> str:
    """Format an If-condition function call (e.g. DoesRegKeyExist, DoesFileExist)."""
    formatted_args: list[str] = []

    if fn.function.lower() == "doesregkeyexist" and fn.args:
        if len(fn.args) == 1:
            first_arg = fn.args[0]
            raw_arg = first_arg.text if isinstance(first_arg, LiteralValue) else str(first_arg)
            clean_arg = raw_arg.strip('"').strip("'")
            if "," in clean_arg:
                root_part, rest = clean_arg.split(",", 1)
                if "," in rest:
                    key_part, val_part = rest.rsplit(",", 1)
                    key_quoted = q_reg_component(key_part, issues)
                    arg_str = f'"{root_part},{key_quoted},{val_part}"'
                else:
                    key_quoted = q_reg_component(rest, issues)
                    arg_str = f'"{root_part},{key_quoted}"'
                return f"{fn.function} ({arg_str})"
            return f'{fn.function} ("{clean_arg}")'
        elif len(fn.args) >= 2:
            root_part = str(fn.args[0])
            key_part = q_reg_component(str(fn.args[1]), issues)
            val_part = f",{fn.args[2]}" if len(fn.args) > 2 else ""
            arg_str = f'"{root_part},{key_part}{val_part}"'
            return f"{fn.function} ({arg_str})"

    for a in fn.args:
        if isinstance(a, (VarRef, IndirectVar, IniRef, RegistryRef)):
            formatted_args.append(q_value(a, issues))
        else:
            val_str = a.text if isinstance(a, LiteralValue) else str(a)
            if val_str.startswith('"') and val_str.endswith('"'):
                formatted_args.append(val_str)
            else:
                formatted_args.append(f'"{val_str}"')

    args_rendered = ", ".join(formatted_args)
    return f"{fn.function} ({args_rendered})"


def q_cond_operand(op: Value | FunctionCall | str, issues: list[Issue] | None = None) -> str:
    """Format an operand in an If comparison (F-06)."""
    if isinstance(op, FunctionCall):
        return q_function_call(op, issues)

    if isinstance(op, (VarRef, IndirectVar, IniRef, RegistryRef)):
        raw = q_value(op, issues)
        return f'"{raw}"' if not (raw.startswith('"') and raw.endswith('"')) else raw

    val_str = op.text if isinstance(op, LiteralValue) else str(op)
    if val_str.startswith('"') and val_str.endswith('"'):
        return val_str

    # Guard: never wrap function calls in outer quotes
    # (Setup.exe would treat them as literal strings)
    known_funcs = (
        "DoesFileExist",
        "DoesPathExist",
        "DoesRegKeyExist",
        "DoesProcessExist",
        "DoesTextInFileExist",
        "FileVersion",
        "FileSize",
        "IsDotNetVersionAvailable",
        "GetDiskFreeSpaceKB",
    )
    trimmed = val_str.strip()
    for fn in known_funcs:
        if trimmed.startswith(f"{fn}(") or trimmed.startswith(f"{fn} ("):
            return trimmed

    return f'"{val_str}"'


def q_condition(cond: Condition, issues: list[Issue] | None = None) -> str:
    """Render complete Condition expression."""
    if isinstance(cond, Comparison):
        left_str = q_cond_operand(cond.left, issues)
        right_str = q_cond_operand(cond.right, issues)
        return f"{left_str} {cond.relation} {right_str}"

    if isinstance(cond, GroupCondition):
        rendered_terms = [f"({q_condition(t, issues)})" for t in cond.terms]
        op_str = f" {cond.op} "
        return op_str.join(rendered_terms)

    if isinstance(cond, FunctionCall):
        return q_function_call(cond, issues)

    return str(cond)


def q_if_statement(stmt: IfStmt, issues: list[Issue] | None = None) -> str:
    """Render If statement with quoted targets (F-05)."""
    cond_str = q_condition(stmt.condition, issues)
    target = stmt.then_target
    then_target_str = f'"{target}"' if not target.startswith('"') else target

    res = f"If {cond_str} Then {then_target_str}"
    if stmt.else_target:
        else_target = stmt.else_target
        else_target_str = f'"{else_target}"' if not else_target.startswith('"') else else_target
        res += f" Else {else_target_str}"
    res += " EndIf"
    return res


def q_call_statement(stmt: CallStmt, issues: list[Issue] | None = None) -> str:
    """Render Call, CallHidden, or CallRunAs (F-02, F-03, F-17)."""
    prefix = "-" if stmt.uninstall_only else ""
    prog_str = q_call_token(stmt.program, issues, is_program=True)

    args_list: list[str] = []
    if stmt.runas_user:
        args_list.append(f"/U:{stmt.runas_user}")
    if stmt.runas_password_ref:
        args_list.append(f"/P:{stmt.runas_password_ref}")

    for arg in stmt.arguments:
        args_list.append(q_call_token(arg, issues, is_program=False))

    args_str = " " + " ".join(args_list) if args_list else ""
    line = f"{prefix}{stmt.name} {prog_str}{args_str}"
    if line.count('"') % 2 != 0:
        line = line + '"'
    return line


def q_command(cmd: Command, issues: list[Issue] | None = None) -> str:
    """Render any general internal command."""
    if isinstance(cmd, CallStmt):
        return q_call_statement(cmd, issues)
    if isinstance(cmd, IfStmt):
        return q_if_statement(cmd, issues)

    prefix = "-" if cmd.uninstall_only else ""

    if isinstance(cmd, SetStmt):
        if isinstance(cmd.value, FunctionCall):
            val_str = q_function_call(cmd.value, issues)
        else:
            val_str = q_value(cmd.value, issues)
        return f"{prefix}Set {cmd.variable}={val_str}"

    if isinstance(cmd, SetRebootStmt):
        return f"{prefix}SetReboot {cmd.mode}"

    if cmd.name == "Set" and len(cmd.args) >= 2:
        var_name = str(cmd.args[0])
        val_arg = cmd.args[1]
        val_str = q_value(val_arg, issues)
        return f"{prefix}Set {var_name}={val_str}"

    if cmd.name == "SetReboot":
        val = cmd.args[0] if cmd.args else "1"
        return f"{prefix}SetReboot {val}"

    rendered_args: list[str] = []
    for arg in cmd.args:
        rendered_args.append(q_value(arg, issues))

    args_str = " " + ", ".join(rendered_args) if rendered_args else ""
    return f"{prefix}{cmd.name}{args_str}"


def q_section_ref(ref: SectionRef) -> str:
    """Render section reference line (e.g. #Set:Product, DONTDELETE)."""
    force_char = "!" if ref.force else ""
    flags = list(ref.flags)
    if ref.uninstall_only and "DELETE" not in flags:
        flags.append("DELETE")
    flags_part = f", {', '.join(flags)}" if flags else ""
    return f"#{force_char}{ref.target}{flags_part}"


def q_copy_entry(entry: CopyEntry, issues: list[Issue] | None = None) -> str:
    """Render file copy entry: <Disk>:<Source>, <Destination>, <Flags>, <Size> (F-18, F-19)."""
    prefix = "-" if entry.uninstall_only else ""
    if "," in entry.source and issues is not None:
        issues.append(
            Issue(
                code="W2005",
                message=f"Source filename contains comma: '{entry.source}'. Should be avoided.",
                severity="warning",
            )
        )

    flags_str = " ".join(entry.flags) if entry.flags else "NORMAL"
    dest_str = f" {entry.destination}" if entry.destination else " "
    return f"{prefix}{entry.disk}:{entry.source},{dest_str}, {flags_str}, {entry.size}"


def q_reg_entry(entry: RegEntry, issues: list[Issue] | None = None) -> str:
    """Render Registry entry (F-11, F-12, F-17)."""
    prefix = "-" if (entry.uninstall_only or entry.delete) else ""

    key_quoted = q_value(entry.key, issues, force_quote=needs_quotes(entry.key))

    val_part = ""
    v_name = entry.value_name if entry.value_name is not None else entry.delete_value
    if v_name is not None:
        val_quoted = q_value(v_name, issues, force_quote=needs_quotes(v_name))
        val_part = f",{val_quoted}"

    if entry.delete and not entry.data:
        return f"{prefix}{entry.root},{key_quoted}{val_part}"

    rendered_data: list[str] = []
    for d in entry.data:
        d_str = str(d.text if isinstance(d, LiteralValue) else d)
        if len(d_str) == 2 and all(c in "0123456789ABCDEFabcdef" for c in d_str):
            rendered_data.append(d_str.upper())
        elif d_str.startswith("0x") or d_str.isdigit():
            rendered_data.append(d_str)
        else:
            # Literal string registry data: double unbalanced % so Setup.exe treats them as literals (E1005)
            clean_check = re.sub(r"(?<!%)%(?:~[A-Za-z0-9]+|[0-9*])(?!%)", "", d_str)
            if clean_check.count("%") % 2 != 0:
                d_str = d_str.replace("%", "%%")
            rendered_data.append(f'"{d_str}"')

    data_part = f",{','.join(rendered_data)}" if rendered_data else ""
    return f"{prefix}{entry.root},{key_quoted}{val_part},{entry.type_flag}{data_part}"


def q_shell_entry(entry: ShellEntry, issues: list[Issue] | None = None) -> str:
    """Render Shell shortcut entry preserving empty comma columns (Q-13)."""
    prefix = "-" if entry.uninstall_only else ""
    link_str = q_value(entry.link, issues)
    cmd_str = q_value(entry.command, issues)
    args_str = q_value(entry.arguments, issues) if entry.arguments else ""
    workdir_str = q_value(entry.workdir, issues) if entry.workdir else ""
    desc_str = q_value(entry.description, issues) if entry.description else ""
    icon_file_str = q_value(entry.icon_file, issues) if entry.icon_file else ""
    icon_idx_str = str(entry.icon_index) if entry.icon_index != 0 else ""
    win_state_str = str(entry.window_state) if entry.window_state != 1 else ""
    hotkey_str = str(entry.hotkey) if entry.hotkey != 0 else ""

    parts = [
        link_str,
        cmd_str,
        args_str,
        workdir_str,
        desc_str,
        icon_file_str,
        icon_idx_str,
        win_state_str,
        hotkey_str,
    ]
    while len(parts) > 2 and parts[-1] == "":
        parts.pop()

    return f"{prefix}{','.join(parts)}"
