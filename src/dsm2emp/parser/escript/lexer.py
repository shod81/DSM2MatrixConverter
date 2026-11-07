import re

from dsm2emp.parser.ir import (
    IrCompositeValue,
    IrFallbackVar,
    IrLiteral,
    IrNestedVar,
    IrValue,
    IrVarRef,
)

# Regular expression for %[~(int)Var~Fallback]% or %[~Var~Fallback]%
RE_FALLBACK_VAR = re.compile(
    r"^%\[~(?:\((?P<type>int)\))?(?P<name>[^~%]+)~(?P<fallback>[^\]]*)\]%$"
)

# Regular expression for %[Outer%Inner%]%
RE_NESTED_VAR = re.compile(r"^%\[(?P<outer>[^%]+)%(?P<inner>[^%]+)%\]%$")


def unquote(s: str) -> str:
    """Remove matching surrounding single or double quotes."""
    s = s.strip()
    if len(s) >= 2:
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            inner = s[1:-1]
            if s.startswith("'"):
                return inner.replace("''", "'")
            return inner.replace(r"\"", '"')
    return s


def parse_dsm_value(text: str) -> IrValue:
    """Parse a DSM string into typed IrValue (handling %, %%, %[], %[~])."""
    # Clean surrounding quotes first if whole string is quoted
    val_str = unquote(text)

    # 1. Check for fallback variable: %[~Var~Default]% or %[~(int)Var~0]%
    m_fb = RE_FALLBACK_VAR.match(val_str)
    if m_fb:
        is_int = m_fb.group("type") == "int"
        name = m_fb.group("name")
        fallback = m_fb.group("fallback")
        return IrFallbackVar(name=name, fallback=fallback, is_int=is_int)

    # 2. Check for nested variable: %[Outer%Inner%]%
    m_nest = RE_NESTED_VAR.match(val_str)
    if m_nest:
        outer = m_nest.group("outer")
        inner_name = m_nest.group("inner")
        return IrNestedVar(outer=outer, inner=IrVarRef(name=inner_name))

    # 3. Check for single variable: %Name% (and not containing other text)
    if val_str.startswith("%") and val_str.endswith("%") and val_str.count("%") == 2:
        inner = val_str[1:-1]
        if inner != "":  # Not "%%"
            return IrVarRef(name=inner)

    # 4. Tokenize composite text with literals and variables
    parts: list[IrValue] = []
    i = 0
    n = len(val_str)
    current_lit: list[str] = []

    while i < n:
        # Check for escaped %% -> literal %
        if val_str[i : i + 2] == "%%":
            current_lit.append("%")
            i += 2
            continue

        # Check for start of variable %[ or %
        if val_str[i : i + 2] == "%[":
            end_bracket = val_str.find("]%", i + 2)
            if end_bracket != -1:
                if current_lit:
                    parts.append(IrLiteral(value="".join(current_lit)))
                    current_lit = []
                chunk = val_str[i : end_bracket + 2]
                parts.append(parse_dsm_value(chunk))
                i = end_bracket + 2
                continue

        if val_str[i] == "%":
            end_pct = val_str.find("%", i + 1)
            if end_pct != -1:
                # Variable found
                var_name = val_str[i + 1 : end_pct]
                if var_name:  # non-empty
                    if current_lit:
                        parts.append(IrLiteral(value="".join(current_lit)))
                        current_lit = []
                    parts.append(IrVarRef(name=var_name))
                    i = end_pct + 1
                    continue

        current_lit.append(val_str[i])
        i += 1

    if current_lit:
        parts.append(IrLiteral(value="".join(current_lit)))

    if not parts:
        return IrLiteral(value="")
    if len(parts) == 1:
        return parts[0]
    return IrCompositeValue(parts=parts)


def split_arguments(args_str: str) -> list[str]:
    """Split argument string by commas respecting quotes and parentheses."""
    args: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    paren_depth = 0
    i = 0
    n = len(args_str)

    while i < n:
        c = args_str[i]

        if c == "'" and not in_double:
            # Check for escaped '' inside single quotes
            if in_single and i + 1 < n and args_str[i + 1] == "'":
                current.append("''")
                i += 2
                continue
            in_single = not in_single
            current.append(c)
        elif c == '"' and not in_single:
            # Check for escaped \" inside double quotes
            if in_double and i > 0 and args_str[i - 1] == "\\":
                current.append(c)
            else:
                in_double = not in_double
                current.append(c)
        elif c == "(" and not in_single and not in_double:
            paren_depth += 1
            current.append(c)
        elif c == ")" and not in_single and not in_double:
            paren_depth -= 1
            current.append(c)
        elif c == "," and not in_single and not in_double and paren_depth == 0:
            arg = "".join(current).strip()
            args.append(arg)
            current = []
        else:
            current.append(c)
        i += 1

    if current:
        arg = "".join(current).strip()
        args.append(arg)

    return args


def extract_command_parts(line: str) -> tuple[str, list[str], list[str]]:
    """Parse a single command line into (command_name, [raw_arguments], [flags]).

    Handles:
      Command('arg1', 'arg2')/TS
      Command('arg1', 'arg2')/U/TS
      Command('arg1', 'arg2')
      Command/TS
      Command arg1 arg2
      Command
    """
    clean = line.strip()
    if not clean:
        return "", [], []

    flags: list[str] = []
    paren_idx = clean.find("(")
    if paren_idx != -1:
        # Check if paren is part of command call (not inside quotes)
        in_single = False
        in_double = False
        paren_depth = 0
        close_idx = -1
        for i, c in enumerate(clean):
            if c == "'" and not in_double:
                in_single = not in_single
            elif c == '"' and not in_single:
                in_double = not in_double
            elif not in_single and not in_double:
                if c == "(":
                    paren_depth += 1
                elif c == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        close_idx = i
                        break
        if close_idx != -1:
            cmd_name = clean[:paren_idx].strip()
            args_body = clean[paren_idx + 1 : close_idx].strip()
            trailing = clean[close_idx + 1 :].strip()
            if trailing:
                flags = [f.lstrip("/").upper() for f in re.findall(r"/[A-Za-z0-9_]+", trailing)]
            raw_args = split_arguments(args_body) if args_body else []
            return cmd_name, raw_args, flags

    # No parens: e.g. EndProc/TS, Sleep 5
    m = re.search(r"((?:/[A-Za-z0-9_]+)+)\s*$", clean)
    if m:
        flags = [f.lstrip("/").upper() for f in re.findall(r"/[A-Za-z0-9_]+", m.group(1))]
        clean = clean[: m.start()].strip()

    parts = clean.split(maxsplit=1)
    cmd_name = parts[0] if parts else ""
    raw_args = split_arguments(parts[1]) if len(parts) > 1 else []
    return cmd_name, raw_args, flags


def split_command_line(line: str) -> tuple[str, list[str]]:
    """Parse a single command line into (command_name, [raw_arguments])."""
    cmd_name, raw_args, _ = extract_command_parts(line)
    return cmd_name, raw_args
