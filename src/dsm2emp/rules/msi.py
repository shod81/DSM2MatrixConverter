"""MSI utility functions for validating GUIDs and resolving MSI targets (pure domain)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

_GUID_REGEX = re.compile(
    r"^\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}$"
)


def is_valid_guid(text: str) -> bool:
    """Check if string is a valid Windows Installer GUID enclosed in braces."""
    return bool(_GUID_REGEX.match(text.strip()))


def extract_product_code_from_msi_binary(msi_path: Path | str) -> str | None:
    """Pure-Python fallback to find embedded ProductCode in an MSI/mock binary file."""
    p = Path(msi_path)
    if not p.is_file():
        return None
    try:
        with open(p, "rb") as f:
            data = f.read(32 * 1024 * 1024)

        m_near = re.search(
            rb"ProductCode.{0,128}?(\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\})",
            data,
            re.DOTALL | re.IGNORECASE,
        )
        if m_near:
            guid_str = m_near.group(1).decode("ascii", errors="ignore").upper()
            if is_valid_guid(guid_str):
                return guid_str
    except Exception:
        pass
    return None


# Backward-compatible alias within rules
extract_product_code_from_msi = extract_product_code_from_msi_binary


def resolve_msi_guid(
    msi_target: str,
    package_root: Path | None = None,
    media_files: Sequence[Path] | None = None,
    msi_product_codes: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve an MSI target string (filename, path, or existing GUID) to its ProductCode GUID.

    If the target is already a GUID, returns it directly.
    If pre-extracted in msi_product_codes, looks up the GUID.
    If the file exists in the package payload or filesystem, attempts pure-Python extraction.
    If cannot be resolved or extracted, returns None.
    """
    clean_target = msi_target.strip().strip("'\"")
    if not clean_target:
        return None

    if is_valid_guid(clean_target):
        return clean_target.upper()

    norm = clean_target.replace("/", "\\")
    for prefix in (
        "%SRC%\\Files\\",
        "%SRC%\\",
        "%src%\\files\\",
        "%src%\\",
        ".\\",
        ".\\Extern$\\",
    ):
        if norm.lower().startswith(prefix.lower()):
            norm = norm[len(prefix) :]
            break

    target_name = Path(norm).name

    # Check pre-extracted dictionary from scanner if available
    if msi_product_codes:
        for key in (clean_target, norm, target_name):
            if key in msi_product_codes:
                val = msi_product_codes[key]
                if is_valid_guid(val):
                    return val.upper()
        # Case-insensitive lookup
        lower_map = {k.lower(): v for k, v in msi_product_codes.items()}
        for key in (clean_target.lower(), norm.lower(), target_name.lower()):
            if key in lower_map:
                val = lower_map[key]
                if is_valid_guid(val):
                    return val.upper()

    candidates: list[Path] = []

    # 1. Direct path
    try:
        direct = Path(clean_target)
        if direct.is_file():
            candidates.append(direct)
    except Exception:
        pass

    # 2. Package root search
    if package_root and package_root.is_dir():
        for sub in (
            norm,
            f"Extern$\\{norm}",
            f"Files\\{norm}",
            target_name,
            f"Extern$\\{target_name}",
            f"Files\\{target_name}",
        ):
            cand = package_root / sub
            if cand.is_file() and cand not in candidates:
                candidates.append(cand)
        if not candidates and target_name:
            for p in package_root.glob(f"**/{target_name}"):
                if p.is_file() and p not in candidates:
                    candidates.append(p)
                    break

    # 3. Media files from inventory
    if media_files:
        for m in media_files:
            if m.name.lower() == target_name.lower() and m.is_file() and m not in candidates:
                candidates.append(m)

    for cand in candidates:
        guid = extract_product_code_from_msi_binary(cand)
        if guid:
            return guid

    return None
