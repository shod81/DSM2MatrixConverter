"""Parser for Empirum Setup.inf text into a typed InfDocument AST."""

import re
from typing import Any, Literal

from dsm2emp.ast.nodes import (
    CallStmt,
    Command,
    Comment,
    Comparison,
    Condition,
    CopyEntry,
    EmptyLine,
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
from dsm2emp.ast.values import LiteralValue, Value, VarRef


def _tokenize_line(text: str) -> list[str]:
    """Tokenize a line respecting double and single quotes."""
    tokens: list[str] = []
    current: list[str] = []
    in_dquote = False
    in_squote = False

    for c in text:
        if c == '"' and not in_squote:
            in_dquote = not in_dquote
            current.append(c)
        elif c == "'" and not in_dquote:
            in_squote = not in_squote
            current.append(c)
        elif (c in (" ", "\t", ",")) and not in_dquote and not in_squote:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(c)

    if current:
        tokens.append("".join(current))

    return tokens


def _determine_section_kind(name: str) -> tuple[SectionKind, str | None]:
    name_lower = name.lower()
    meta_sections = (
        "setupinfo",
        "setup",
        "vardefinfo",
        "requirements",
        "application",
        "environment",
    )
    if name_lower in meta_sections:
        return SectionKind.META, None
    if name_lower == "options":
        return SectionKind.OPTIONS, None
    if (
        name_lower in ("disks", "processes", "installer", "encryption")
        or name_lower.startswith("strings:")
        or name_lower.startswith("sysstrings:")
    ):
        return SectionKind.SUPPORT, None
    if name_lower.startswith("reg:"):
        return SectionKind.TYPED, "Reg:"
    if name_lower.startswith("ini:"):
        return SectionKind.TYPED, "Ini:"
    if name_lower.startswith("shell:"):
        return SectionKind.TYPED, "Shell:"
    if name_lower.startswith("security:"):
        return SectionKind.TYPED, "Security:"
    return SectionKind.WORK, None


def _parse_single_condition(cond_str: str) -> Condition:
    """Parse a single condition without top-level logical operators."""
    clean = cond_str.strip()
    if clean.startswith("(") and clean.endswith(")"):
        clean = clean[1:-1].strip()

    # Support <> with or without space (e.g. "%MSIGUID_X86%"<> "")
    for rel in ("==", "!=", "<=", ">=", "<>", "<", ">", "="):
        # Look for rel surrounded by spaces or immediately adjacent
        pattern = f" {rel} "
        if pattern in clean:
            parts = clean.split(pattern, 1)
        elif rel in clean:
            parts = clean.split(rel, 1)
        else:
            continue

        left_raw = parts[0].strip().strip('"')
        right_raw = parts[1].strip().strip('"')

        left_val: Value | FunctionCall | str
        if "(" in left_raw and left_raw.endswith(")"):
            fn_name, fn_args_raw = left_raw.split("(", 1)
            left_val = FunctionCall(
                function=fn_name.strip(),
                args=[fn_args_raw[:-1].strip().strip('"')],
            )
        elif left_raw.startswith("%") and left_raw.endswith("%"):
            left_val = VarRef(name=left_raw.strip("%"))
        else:
            left_val = LiteralValue(text=left_raw)

        right_val: Value | FunctionCall | str
        if right_raw.startswith("%") and right_raw.endswith("%"):
            right_val = VarRef(name=right_raw.strip("%"))
        else:
            right_val = LiteralValue(text=right_raw)

        valid_rel: Literal["==", "=", "!=", "<>", "<", "<=", ">", ">="] = rel
        return Comparison(left=left_val, relation=valid_rel, right=right_val)

    if "(" in clean and clean.endswith(")"):
        fn_name, fn_args_raw = clean.split("(", 1)
        return FunctionCall(
            function=fn_name.strip(),
            args=[fn_args_raw[:-1].strip().strip('"')],
        )

    # Fallback to comparison against "1"
    return Comparison(
        left=LiteralValue(text=clean),
        relation="==",
        right=LiteralValue(text="1"),
    )


def _parse_if_condition(cond_str: str) -> Condition:
    """Parse compound or single If condition expression."""
    clean = cond_str.strip()
    if " | " in clean:
        parts = clean.split(" | ")
        terms = [_parse_single_condition(p) for p in parts]
        return GroupCondition(terms=terms, op="|")
    if " & " in clean:
        parts = clean.split(" & ")
        terms = [_parse_single_condition(p) for p in parts]
        return GroupCondition(terms=terms, op="&")

    return _parse_single_condition(clean)


def _parse_command_line(line: str) -> Command:
    """Parse command line like Call, Set, SetReboot, If, Del, etc."""
    stripped = line.strip()
    uninstall_only = stripped.startswith("-")
    if uninstall_only:
        stripped = stripped[1:].strip()

    # Case-insensitive If statement (e.g. EndIF / EndIf / ENDIF)
    upper_line = stripped.upper()
    if upper_line.startswith("IF ") and " THEN " in upper_line and upper_line.endswith("ENDIF"):
        then_pos = upper_line.index(" THEN ")
        cond_str = stripped[3:then_pos].strip()
        rest = stripped[then_pos + 6 : -5].strip()

        upper_rest = rest.upper()
        if " ELSE " in upper_rest:
            else_pos = upper_rest.index(" ELSE ")
            then_part = rest[:else_pos].strip()
            else_part = rest[else_pos + 6 :].strip()
            then_target = then_part.strip().strip('"')
            else_target = else_part.strip().strip('"')
        else:
            then_target = rest.strip().strip('"')
            else_target = None

        cond = _parse_if_condition(cond_str)
        return IfStmt(
            condition=cond,
            then_target=then_target,
            else_target=else_target,
            uninstall_only=uninstall_only,
        )

    # Set statement: Set <Var> = <Val> or Set <Var>=<Val> (Empirum is case-insensitive)
    if upper_line.startswith("SET ") and "=" in stripped:
        set_body = stripped[4:].strip()
        var_name, val_str = set_body.split("=", 1)
        return SetStmt(
            variable=var_name.strip(),
            value=val_str.strip().strip('"'),
            uninstall_only=uninstall_only,
        )

    # SetReboot: SetReboot <mode> | SetReboot=<mode> | SetReboot(<mode>)
    if upper_line.startswith("SETREBOOT"):
        rest = stripped[len("SetReboot") :].strip()
        if rest.startswith("="):
            rest = rest[1:].strip()
        if rest.startswith("(") and rest.endswith(")"):
            rest = rest[1:-1].strip()
        mode_val = int(rest) if rest.isdigit() else 1
        return SetRebootStmt(mode=mode_val, uninstall_only=uninstall_only)

    # Call / CallHidden / CallRunAs (Empirum is case-insensitive)
    call_prefixes: tuple[Literal["CallRunAsHidden", "CallRunAs", "CallHidden", "Call"], ...] = (
        "CallRunAsHidden",
        "CallRunAs",
        "CallHidden",
        "Call",
    )
    for call_prefix in call_prefixes:
        prefix_upper = call_prefix.upper()
        match_call = (
            upper_line == prefix_upper
            or upper_line.startswith(f"{prefix_upper} ")
            or upper_line.startswith(f"{prefix_upper}\t")
        )
        if match_call:
            tokens = _tokenize_line(stripped[len(call_prefix) :].strip())
            prog = tokens[0] if tokens else ""
            args = tokens[1:] if len(tokens) > 1 else []
            return CallStmt(
                name=call_prefix,
                program=prog.strip('"'),
                arguments=[a.strip('"') for a in args],
                uninstall_only=uninstall_only,
            )

    # General Command
    parts = stripped.split(None, 1)
    cmd_name = parts[0]
    args_raw = parts[1] if len(parts) > 1 else ""
    tokens = _tokenize_line(args_raw)
    return Command(
        name=cmd_name,
        args=[t.strip('"') for t in tokens],
        uninstall_only=uninstall_only,
    )


def parse_setup_inf(text: str) -> InfDocument:
    """Parse Setup.inf text into an InfDocument AST."""
    text = text.lstrip("\ufeff")
    sections: list[Section] = []
    current_sec: Section | None = None
    current_lines: list[SectionLine] = []

    def commit_section() -> None:
        nonlocal current_sec, current_lines
        if current_sec is not None:
            while current_lines and isinstance(current_lines[0], EmptyLine):
                current_lines.pop(0)
            while current_lines and isinstance(current_lines[-1], EmptyLine):
                current_lines.pop()

            kind, prefix = _determine_section_kind(current_sec.name)
            sections.append(
                Section(
                    name=current_sec.name,
                    kind=kind,
                    typed_prefix=prefix,
                    lines=current_lines,
                )
            )
            current_sec = None
            current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        # Empty line
        if not line:
            if current_sec is not None:
                current_lines.append(EmptyLine())
            continue

        # Comment line
        if line.startswith(";") or line.lower().startswith("rem "):
            style: Literal["semicolon", "rem"] = "semicolon" if line.startswith(";") else "rem"
            if line.startswith(";"):
                raw_comment = line[1:]
                comment_text = raw_comment[1:] if raw_comment.startswith(" ") else raw_comment
            else:
                comment_text = line[4:].lstrip()
            if current_sec is not None:
                current_lines.append(Comment(text=comment_text, style=style))
            continue

        # Section header: [Name]
        if line.startswith("[") and line.endswith("]"):
            commit_section()
            sec_name = line[1:-1].strip()
            kind, prefix = _determine_section_kind(sec_name)
            current_sec = Section(name=sec_name, kind=kind, typed_prefix=prefix, lines=[])
            continue

        if current_sec is None:
            continue

        uninstall_only = line.startswith("-")
        clean_line = line[1:].strip() if uninstall_only else line

        # Section reference: #Name or #!Name
        if clean_line.startswith("#"):
            ref_body = clean_line[1:].strip()
            force = ref_body.startswith("!")
            if force:
                ref_body = ref_body[1:].strip()
            parts = [p.strip() for p in ref_body.split(",")]
            target = parts[0]
            flags = parts[1:] if len(parts) > 1 else []
            current_lines.append(
                SectionRef(
                    target=target,
                    force=force,
                    flags=flags,
                    uninstall_only=uninstall_only,
                )
            )
            continue

        # Copy line: 1:Source, Destination, Flags, Size
        if re.match(r"^\d+:", clean_line):
            colon_idx = clean_line.index(":")
            disk_num = int(clean_line[:colon_idx])
            rest = clean_line[colon_idx + 1 :]
            tokens = [t.strip() for t in rest.split(",")]
            src = tokens[0] if len(tokens) > 0 else ""
            dst = tokens[1] if len(tokens) > 1 else ""
            flags_str = tokens[2] if len(tokens) > 2 else ""
            size_val = int(tokens[3]) if len(tokens) > 3 and tokens[3].isdigit() else 0
            copy_flags = flags_str.split() if flags_str else []
            current_lines.append(
                CopyEntry(
                    disk=disk_num,
                    source=src,
                    destination=dst,
                    flags=copy_flags,
                    size=size_val,
                    uninstall_only=uninstall_only,
                )
            )
            continue

        # Typed sections
        if current_sec.kind == SectionKind.TYPED and current_sec.name.lower().startswith("reg:"):
            tokens = _tokenize_line(clean_line)
            if tokens:
                root = tokens[0]
                key = tokens[1].strip('"').strip("'") if len(tokens) > 1 else ""
                val_name: str | None = None
                type_flag = "0x00000000"
                data_list: list[Any] = []

                if len(tokens) > 2:
                    if tokens[2].startswith("0x"):
                        type_flag = tokens[2]
                        data_list = [d.strip('"') for d in tokens[3:]]
                    else:
                        val_name = tokens[2].strip('"')
                        if len(tokens) > 3:
                            type_flag = tokens[3]
                            data_list = [d.strip('"') for d in tokens[4:]]

                current_lines.append(
                    RegEntry(
                        root=root,
                        key=key,
                        value_name=val_name,
                        type_flag=type_flag,
                        data=data_list,
                        delete=uninstall_only,
                        uninstall_only=uninstall_only,
                    )
                )
            continue

        if current_sec.kind == SectionKind.TYPED and current_sec.name.lower().startswith("shell:"):
            tokens = [t.strip() for t in clean_line.split(",")]
            link = tokens[0] if len(tokens) > 0 else ""
            cmd = tokens[1] if len(tokens) > 1 else ""
            args = tokens[2] if len(tokens) > 2 else ""
            workdir = tokens[3] if len(tokens) > 3 else ""
            desc = tokens[4] if len(tokens) > 4 else ""
            icon = tokens[5] if len(tokens) > 5 else ""
            current_lines.append(
                ShellEntry(
                    link=link,
                    command=cmd,
                    arguments=args,
                    workdir=workdir,
                    description=desc,
                    icon_file=icon,
                    uninstall_only=uninstall_only,
                )
            )
            continue

        # Meta/Options/Support sections: Key=Value
        is_meta_like = current_sec.kind in (
            SectionKind.META,
            SectionKind.SUPPORT,
            SectionKind.OPTIONS,
        )
        if is_meta_like and "=" in clean_line:
            key, val = clean_line.split("=", 1)
            raw_val = val.strip()
            # Preserve quoted string if it was quoted in source
            current_lines.append(KeyValue(key=key.strip(), value=raw_val))
            continue

        # Default: parse as command
        current_lines.append(_parse_command_line(line))

    commit_section()
    return InfDocument(sections=sections)
