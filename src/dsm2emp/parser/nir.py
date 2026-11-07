"""Parser for DSM NIR and Windows REG files.

Parses REGEDIT4 and Windows Registry Editor Version 5.00 files into typed
registry intermediate representation (IR) preserving DSM variables and operations.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dsm2emp.parser.escript.lexer import parse_dsm_value
from dsm2emp.parser.ir import IrValue, SourceRef

RegistryValueType = Literal[
    "REG_SZ",
    "REG_DWORD",
    "REG_BINARY",
    "REG_EXPAND_SZ",
    "REG_MULTI_SZ",
    "REG_QWORD",
    "REG_NONE",
    "DELETE",
]

REG_ROOT_MAP: dict[str, str] = {
    "hkey_local_machine": "HKLM",
    "hklm": "HKLM",
    "hkey_current_user": "HKCU",
    "hkcu": "HKCU",
    "hkey_classes_root": "HKCR",
    "hkcr": "HKCR",
    "hkey_users": "HKU",
    "hku": "HKU",
    "hkey_current_config": "HKCC",
    "hkcc": "HKCC",
}
ROOT_MAP = REG_ROOT_MAP


class IrRegValue(BaseModel):
    """Represents a single registry key value or value deletion."""

    model_config = ConfigDict(frozen=True)

    name: str  # "" for default @ value
    val_type: RegistryValueType
    raw_data: str
    parsed_value: IrValue | None = None
    dword_int: int | None = None
    is_delete: bool = False


class IrRegKey(BaseModel):
    """Represents a registry key section with its values or key deletion."""

    model_config = ConfigDict(frozen=True)

    root: str  # HKLM, HKCU, HKCR, HKU, HKCC
    path: str
    is_delete: bool = False
    values: list[IrRegValue] = Field(default_factory=list)
    src: SourceRef


def _unescape_reg_string(s: str) -> str:
    """Unescape standard registry string escapes (\\\\ -> \\, \\\" -> \")."""
    res: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            next_char = s[i + 1]
            if next_char in ("\\", '"'):
                res.append(next_char)
                i += 2
                continue
            if next_char == "n":
                res.append("\n")
                i += 2
                continue
            if next_char == "r":
                res.append("\r")
                i += 2
                continue
        res.append(s[i])
        i += 1
    return "".join(res)


def _parse_reg_value_assignment(name_part: str, value_part: str) -> IrRegValue:
    """Parse name and value parts of a registry entry."""
    val_name = ""
    clean_name = name_part.strip()
    if clean_name != "@":
        # Strip surrounding quotes
        if clean_name.startswith('"') and clean_name.endswith('"'):
            val_name = _unescape_reg_string(clean_name[1:-1])
        else:
            val_name = clean_name

    val_data = value_part.strip()

    # 1. Deletion: "Value"=-
    if val_data == "-":
        return IrRegValue(
            name=val_name,
            val_type="DELETE",
            raw_data="-",
            is_delete=True,
        )

    # 2. String: "Value"="String"
    if val_data.startswith('"') and val_data.endswith('"'):
        unescaped = _unescape_reg_string(val_data[1:-1])
        parsed = parse_dsm_value(unescaped)
        return IrRegValue(
            name=val_name,
            val_type="REG_SZ",
            raw_data=val_data,
            parsed_value=parsed,
        )

    # 3. DWORD: "Value"=dword:00000001
    if val_data.lower().startswith("dword:"):
        hex_str = val_data[6:].strip()
        try:
            int_val = int(hex_str, 16)
        except ValueError:
            int_val = 0
        return IrRegValue(
            name=val_name,
            val_type="REG_DWORD",
            raw_data=val_data,
            dword_int=int_val,
        )

    # 4. Multi-string: "Value"=hex(7):...
    if val_data.lower().startswith("hex(7):"):
        return IrRegValue(
            name=val_name,
            val_type="REG_MULTI_SZ",
            raw_data=val_data[7:].strip(),
        )

    # 5. Expand string: "Value"=hex(2):...
    if val_data.lower().startswith("hex(2):"):
        return IrRegValue(
            name=val_name,
            val_type="REG_EXPAND_SZ",
            raw_data=val_data[7:].strip(),
        )

    # 6. QWORD: "Value"=hex(b):...
    if val_data.lower().startswith("hex(b):"):
        return IrRegValue(
            name=val_name,
            val_type="REG_QWORD",
            raw_data=val_data[7:].strip(),
        )

    # 7. Binary: "Value"=hex:...
    if val_data.lower().startswith("hex:"):
        return IrRegValue(
            name=val_name,
            val_type="REG_BINARY",
            raw_data=val_data[4:].strip(),
        )

    # Fallback to REG_SZ or REG_NONE
    return IrRegValue(
        name=val_name,
        val_type="REG_NONE",
        raw_data=val_data,
    )


def parse_nir(text: str, file_path: Path) -> list[IrRegKey]:
    """Parse NIR or REG file content into a list of IrRegKey models."""
    # First join lines with backslash continuations
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    joined_lines: list[tuple[int, str]] = []
    accum: list[str] = []
    start_line = 1

    for line_idx, line in enumerate(raw_lines, 1):
        stripped_right = line.rstrip()
        if stripped_right.endswith("\\"):
            content = stripped_right[:-1]
            if not accum:
                start_line = line_idx
                accum.append(content)
            else:
                accum.append(content.strip())
        else:
            if accum:
                accum.append(line.strip())
                joined_lines.append((start_line, "".join(accum)))
                accum = []
            else:
                joined_lines.append((line_idx, line.strip()))

    keys: list[IrRegKey] = []
    current_key: IrRegKey | None = None
    current_values: list[IrRegValue] = []

    def commit_key() -> None:
        nonlocal current_key, current_values
        if current_key:
            keys.append(
                IrRegKey(
                    root=current_key.root,
                    path=current_key.path,
                    is_delete=current_key.is_delete,
                    values=current_values,
                    src=current_key.src,
                )
            )
            current_key = None
            current_values = []

    for line_idx, line in joined_lines:
        if not line:
            continue
        # Comments (; or // or #)
        if line.startswith(";") or line.startswith("//") or line.startswith("#"):
            continue

        # Header lines: REGEDIT4 or Windows Registry Editor Version 5.00
        if "regedit4" in line.lower() or "windows registry editor" in line.lower():
            continue

        # Key header: [HKEY_...] or [-HKEY_...]
        if line.startswith("[") and line.endswith("]"):
            commit_key()
            inner = line[1:-1].strip()
            is_delete = False
            if inner.startswith("-"):
                is_delete = True
                inner = inner[1:].strip()

            parts = inner.split("\\", maxsplit=1)
            root_raw = parts[0].strip()
            subpath = parts[1].strip() if len(parts) > 1 else ""
            root_norm = ROOT_MAP.get(root_raw.lower(), root_raw)

            src = SourceRef(file=file_path, line=line_idx, col=1, raw=line)
            current_key = IrRegKey(
                root=root_norm,
                path=subpath,
                is_delete=is_delete,
                values=[],
                src=src,
            )
            continue

        # Value line: "Name"=Value or @=Value
        if current_key is not None and "=" in line:
            # Match "Name"= or @=
            m = re.match(r'^(@|".*?")\s*=(.*)$', line)
            if m:
                name_part, val_part = m.groups()
                reg_val = _parse_reg_value_assignment(name_part, val_part)
                current_values.append(reg_val)

    commit_key()
    return keys
