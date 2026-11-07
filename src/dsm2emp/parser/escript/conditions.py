"""Condition parser for DSM eScript If-statements."""

import re
from typing import Literal

from dsm2emp.parser.escript.lexer import parse_dsm_value, split_arguments
from dsm2emp.parser.ir import IrCondition

# Order matters: multi-char operators must precede their single-char prefixes,
# otherwise "== " matches as "=" and the second "=" leaks into the right operand.
RE_COMPARISON = re.compile(r"^(.*?)\s*(<=|>=|!=|<>|==|=|<|>)\s*(.*)$")


def parse_single_condition(cond_str: str) -> IrCondition:
    """Parse an individual condition expression into an IrCondition node."""
    clean = cond_str.strip()
    while clean.startswith("(") and clean.endswith(")"):
        depth = 0
        outer_wraps = True
        for i, c in enumerate(clean):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0 and i < len(clean) - 1:
                    outer_wraps = False
                    break
        if outer_wraps:
            clean = clean[1:-1].strip()
        else:
            break

    negated = False
    if clean.lower().startswith("not "):
        negated = True
        clean = clean[4:].strip()
    elif clean.startswith("!"):
        negated = True
        clean = clean[1:].strip()

    # Check for binary comparison (e.g. %ErrorLevel% != '0' or %IsRunningOnX64% = '1')
    m = RE_COMPARISON.match(clean)
    if m:
        left_raw, op, right_raw = m.groups()
        # Standardize <> to !=
        if op == "<>":
            op = "!="

        # Check if left operand is a function call,
        # e.g. DoesFileExist(...) = '1' or RegKeyExists(...) = '1'
        left_clean = left_raw.strip()
        paren_idx = left_clean.find("(")
        if paren_idx != -1 and left_clean.endswith(")"):
            func_name = left_clean[:paren_idx].strip()
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", func_name):
                args_body = left_clean[paren_idx + 1 : -1].strip()
                raw_args = split_arguments(args_body) if args_body else []
                parsed_args = [parse_dsm_value(a) for a in raw_args]
                right_clean = right_raw.strip().strip("'\"")
                if right_clean in ("1", "0"):
                    if op in ("=", "=="):
                        is_neg = (right_clean == "0") ^ negated
                    else:  # !=, <>
                        is_neg = (right_clean == "1") ^ negated
                    return IrCondition(
                        raw=cond_str.strip(),
                        kind="function",
                        negated=is_neg,
                        func_name=func_name,
                        func_args=parsed_args,
                    )

        return IrCondition(
            raw=cond_str.strip(),
            kind="comparison",
            negated=negated,
            left=parse_dsm_value(left_raw.strip()),
            op=op,
            right=parse_dsm_value(right_raw.strip()),
        )

    # Check for function condition (e.g. IsRunningOnX64 or ExistFile('%Src%\app.exe'))
    paren_idx = clean.find("(")
    if paren_idx != -1 and clean.endswith(")"):
        func_name = clean[:paren_idx].strip()
        args_body = clean[paren_idx + 1 : -1].strip()
        raw_args = split_arguments(args_body) if args_body else []
        parsed_args = [parse_dsm_value(a) for a in raw_args]
        return IrCondition(
            raw=cond_str.strip(),
            kind="function",
            negated=negated,
            func_name=func_name,
            func_args=parsed_args,
        )

    # Check for simple identifier conditions like IsRunningOnX64, IsLaptop
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", clean):
        return IrCondition(
            raw=cond_str.strip(),
            kind="function",
            negated=negated,
            func_name=clean,
            func_args=[],
        )

    # Fallback raw condition
    return IrCondition(
        raw=cond_str.strip(),
        kind="raw",
        negated=negated,
    )


def split_condition_expr(cond_text: str) -> tuple[list[str], Literal["|", "&"], bool]:
    """Split condition text respecting quotes and parentheses.

    Detects top-level logical operators (OR/| vs AND/&).
    Returns (tokens, operator, is_mixed).
    """
    clean = cond_text.strip()
    if not clean:
        return [], "|", False

    # Strip outer matching parentheses if they wrap the entire expression
    while clean.startswith("(") and clean.endswith(")"):
        depth = 0
        outer_wraps = True
        for i, c in enumerate(clean):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0 and i < len(clean) - 1:
                    outer_wraps = False
                    break
        if outer_wraps:
            clean = clean[1:-1].strip()
        else:
            break

    tokens: list[str] = []
    current: list[str] = []
    in_dquote = False
    in_squote = False
    depth = 0
    operators_found: list[Literal["|", "&"]] = []

    i = 0
    n = len(clean)
    while i < n:
        c = clean[i]
        if c == '"' and not in_squote:
            in_dquote = not in_dquote
            current.append(c)
            i += 1
        elif c == "'" and not in_dquote:
            in_squote = not in_squote
            current.append(c)
            i += 1
        elif c == "(" and not in_dquote and not in_squote:
            depth += 1
            current.append(c)
            i += 1
        elif c == ")" and not in_dquote and not in_squote:
            depth -= 1
            current.append(c)
            i += 1
        elif depth == 0 and not in_dquote and not in_squote:
            rest = clean[i:]
            m_or_word = re.match(r"^(?:OR|or)\b\s*", rest, re.IGNORECASE)
            m_or_pipe = re.match(r"^\|\s*", rest)
            m_and_word = re.match(r"^(?:AND|and)\b\s*", rest, re.IGNORECASE)
            m_and_amp = re.match(r"^&\s*", rest)

            if m_or_word and (i == 0 or clean[i - 1].isspace()):
                operators_found.append("|")
                tokens.append("".join(current).strip())
                current = []
                i += len(m_or_word.group(0))
            elif m_or_pipe:
                operators_found.append("|")
                tokens.append("".join(current).strip())
                current = []
                i += len(m_or_pipe.group(0))
            elif m_and_word and (i == 0 or clean[i - 1].isspace()):
                operators_found.append("&")
                tokens.append("".join(current).strip())
                current = []
                i += len(m_and_word.group(0))
            elif m_and_amp:
                operators_found.append("&")
                tokens.append("".join(current).strip())
                current = []
                i += len(m_and_amp.group(0))
            else:
                current.append(c)
                i += 1
        else:
            current.append(c)
            i += 1

    if current:
        tokens.append("".join(current).strip())

    tokens = [t for t in tokens if t]

    if not operators_found:
        return tokens, "|", False

    unique_ops = set(operators_found)
    if len(unique_ops) > 1:
        return tokens, "|", True

    return tokens, operators_found[0], False


def parse_condition_expr(
    cond_text: str,
) -> tuple[list[IrCondition], Literal["|", "&"], bool]:
    """Parse condition string into list of conditions, logical operator, and mixed flag."""
    tokens, op, is_mixed = split_condition_expr(cond_text)
    conds = [parse_single_condition(t) for t in tokens if t.strip()]
    return conds, op, is_mixed


def parse_conditions(cond_text: str) -> list[IrCondition]:
    """Parse condition string into list of conditions (backward compatible)."""
    conds, _, _ = parse_condition_expr(cond_text)
    return conds
