"""Setup.inf Serializer and Document Emitter.

Converts a typed InfDocument AST into a clean, valid Empirum Setup.inf file.
Uses exclusively emitter/quote.py for all quoting decisions.
"""

from dataclasses import dataclass
from typing import Literal

from dsm2emp.ast.nodes import (
    Command,
    Comment,
    CopyEntry,
    EmptyLine,
    InfDocument,
    KeyValue,
    RegEntry,
    Section,
    SectionKind,
    SectionRef,
    ShellEntry,
)
from dsm2emp.emitter.quote import (
    Issue,
    q_command,
    q_copy_entry,
    q_key_value,
    q_reg_entry,
    q_section_ref,
    q_shell_entry,
)

CANONICAL_SECTION_ORDER = [
    "setupinfo",
    "vardefinfo",
    "setup",
    "requirements",
    "application",
    "strings:07",
    "strings:09",
    "sysstrings:07",
    "sysstrings:09",
    "environment",
    "encryption",
    "disks",
    "options",
    "processes",
    "installer",
    "product",
]

_WORK_SECTION_KEYWORDS = (
    "repair",
    "install",
    "reinstall",
    "deinstall",
    "reboot",
    "abort",
)


@dataclass(frozen=True)
class EmitOptions:
    """Options controlling Setup.inf serialization."""

    # Empirum requires ANSI (Windows-1252) without BOM; see EmitOptions note
    # in builder.BuilderOptions and Handoff docs/handoff_packagerx/07_Encoding_SetupInf_Fix.md
    charset: Literal["cp1252", "utf-8", "utf-16"] = "cp1252"
    crlf: bool = True
    bom: bool = False
    trailing_newline: bool = True
    align_meta_keys: bool = False


def _section_sort_key(sec: Section) -> tuple[int, str]:
    """Determine sort weight for canonical section ordering."""
    name_lower = sec.name.strip().lower()
    if name_lower in CANONICAL_SECTION_ORDER:
        return (CANONICAL_SECTION_ORDER.index(name_lower), name_lower)

    # Work sections (Set:, Repair, Install, Reinstall, Deinstall, Reboot, Abort)
    if name_lower.startswith("set:") or any(kw in name_lower for kw in _WORK_SECTION_KEYWORDS):
        return (100, name_lower)

    # Typed sections
    if name_lower.startswith("reg:"):
        return (200, name_lower)
    if name_lower.startswith("ini:"):
        return (300, name_lower)
    if name_lower.startswith("security:"):
        return (400, name_lower)
    if name_lower.startswith("shell:"):
        return (500, name_lower)

    # Any other section at the end
    return (900, name_lower)


def emit(doc: InfDocument, opts: EmitOptions | None = None) -> tuple[str, list[Issue]]:
    """Serialize InfDocument into Setup.inf text.

    Returns (rendered_text, issues_list).
    """
    options = opts if opts is not None else EmitOptions()
    issues: list[Issue] = []
    lines: list[str] = []

    # Sort sections in canonical Empirum order
    sorted_sections = sorted(doc.sections, key=_section_sort_key)

    for i, sec in enumerate(sorted_sections):
        if i > 0:
            lines.append("")

        lines.append(f"[{sec.name}]")

        for line in sec.lines:
            if isinstance(line, Comment):
                prefix = ";" if line.style == "semicolon" else "Rem"
                lines.append(f"{prefix} {line.text}".rstrip())
            elif isinstance(line, EmptyLine):
                lines.append("")
            elif isinstance(line, KeyValue):
                sec_issues = (
                    None
                    if (sec.kind == SectionKind.OPTIONS or sec.name.strip().lower() == "options")
                    else issues
                )
                val_rendered = q_key_value(line.value, sec_issues)
                sep = " = " if options.align_meta_keys else "="
                lines.append(f"{line.key}{sep}{val_rendered}")
            elif isinstance(line, SectionRef):
                lines.append(q_section_ref(line))
            elif isinstance(line, CopyEntry):
                lines.append(q_copy_entry(line, issues))
            elif isinstance(line, RegEntry):
                lines.append(q_reg_entry(line, issues))
            elif isinstance(line, ShellEntry):
                lines.append(q_shell_entry(line, issues))
            elif isinstance(line, Command):
                lines.append(q_command(line, issues))
            else:
                lines.append(str(line))

    newline = "\r\n" if options.crlf else "\n"
    rendered = newline.join(lines)
    if options.trailing_newline:
        rendered += newline

    return rendered, issues
