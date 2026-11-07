"""Metadata and configuration extractor for Empirum package manuals."""

from __future__ import annotations

import configparser
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dsm2emp.io.encoding import read_text
from dsm2emp.manual.model import PackageManualInfo
from dsm2emp.parser.expinfo import parse_expinfo_xml

if TYPE_CHECKING:
    from dsm2emp.parser.ir import IrPackage
    from dsm2emp.rules.model import TransformResult
    from dsm2emp.scanner.inventory import PackageInventory


def sanitize_filename(name: str) -> str:
    """Sanitize string for use as a safe file name across Windows filesystems."""
    # Replace characters not permitted in Windows filenames: \ / : * ? " < > |
    sanitized = re.sub(r'[<>:"/\\|?*]+', "_", name)
    # Strip whitespace, dots, and underscores
    cleaned = sanitized.strip().strip("._ ")
    return cleaned or "Softwarepaket"


def _extract_package_metadata(
    inventory: PackageInventory,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Extract product name, version, manufacturer, description, and revision comment."""
    name: str | None = None
    version: str | None = None
    mfg: str | None = None
    desc: str | None = None
    comment: str | None = None

    # 1. Authoritative DSM _ExpInfo.xml
    exp_file: Path | None = None
    for meta_art in inventory.metadata_files:
        if meta_art.rel_path.name.lower() == "_expinfo.xml":
            exp_file = meta_art.absolute_path
            break
    if not exp_file and (inventory.root_path / "_ExpInfo.xml").exists():
        exp_file = inventory.root_path / "_ExpInfo.xml"

    if exp_file:
        parsed_exp = parse_expinfo_xml(exp_file)
        if parsed_exp.name:
            name = parsed_exp.name
        if parsed_exp.version:
            version = parsed_exp.version
        if parsed_exp.manufacturer:
            mfg = parsed_exp.manufacturer
        if parsed_exp.description:
            desc = parsed_exp.description
        if parsed_exp.revision_comment:
            comment = parsed_exp.revision_comment

    # 2. Fall back to package.ini / setup.ini
    for meta_art in inventory.metadata_files:
        if meta_art.rel_path.name.lower() in ("package.ini", "setup.ini"):
            try:
                content, _ = read_text(meta_art.absolute_path)
                cp = configparser.ConfigParser()
                cp.read_string(content)
                for sec in ("Package", "Application", "Setup"):
                    if cp.has_section(sec):
                        name = (
                            name
                            or cp.get(sec, "Name", fallback=None)
                            or cp.get(sec, "ProductName", fallback=None)
                        )
                        version = version or cp.get(sec, "Version", fallback=None)
                        mfg = (
                            mfg
                            or cp.get(sec, "Manufacturer", fallback=None)
                            or cp.get(sec, "DeveloperName", fallback=None)
                        )
                        desc = (
                            desc
                            or cp.get(sec, "Description", fallback=None)
                            or cp.get(sec, "Comment", fallback=None)
                            or cp.get(sec, "Summary", fallback=None)
                        )
            except Exception:
                pass

    return name, version, mfg, desc, comment


def _extract_commands_and_switches(
    inventory: PackageInventory,
    inf_content: str,
) -> tuple[list[str], str]:
    """Extract executed installer commands and primary silent parameters."""
    command_lines: list[str] = []
    detected_switches: list[str] = []

    # 1. Search in Setup.inf lines
    switch_pattern = (
        r"(/qn|/qb|/quiet|/passive|/s\b|/S\b|/silent|/SILENT|/verysilent|"
        r'/VERYSILENT|/norestart|/NORESTART|TRANSFORMS="?[^"\s]+"?)'
    )
    for line in inf_content.splitlines():
        line_clean = line.strip()
        if line_clean.startswith(("Call ", "CallHidden ")):
            command_lines.append(line_clean)
            # Find switches in Call line
            switches = re.findall(switch_pattern, line_clean)
            for sw in switches:
                if sw not in detected_switches:
                    detected_switches.append(sw)

    # 2. Search in main script if commands not yet found
    if not command_lines and inventory.main_script and inventory.main_script.absolute_path.exists():
        try:
            content, _ = read_text(inventory.main_script.absolute_path)
            for line in content.splitlines():
                if "executeex" in line.lower() or "msiinstallproduct" in line.lower():
                    clean = line.strip()
                    command_lines.append(clean)
                    switches = re.findall(switch_pattern, clean)
                    for sw in switches:
                        if sw not in detected_switches:
                            detected_switches.append(sw)
        except Exception:
            pass

    silent_str = " ".join(detected_switches) if detected_switches else ""
    return command_lines, silent_str


def _detect_package_type(
    inventory: PackageInventory,
    inf_content: str,
    commands: list[str],
) -> tuple[str, str]:
    """Detect package installer type and normalize silent parameter representation."""
    has_msi_file = any(a.rel_path.name.lower().endswith(".msi") for a in inventory.media)
    all_text = (inf_content + " " + " ".join(commands)).lower()

    if (
        has_msi_file
        or "msiexec" in all_text
        or "msiinstallproduct" in all_text
        or ".msi" in all_text
    ):
        pkg_type = ".msi (Windows Installer Paket)"
        default_silent = "/qn"
    elif "/verysilent" in all_text or "inno" in all_text:
        pkg_type = "unattend (.exe / Inno Setup)"
        default_silent = "/VERYSILENT /NORESTART"
    elif "/s /v" in all_text or "setup.iss" in all_text or "installshield" in all_text:
        pkg_type = "unattend (.exe / InstallShield)"
        default_silent = '/s /v"/qn"'
    elif any(kw in all_text for kw in ("/s", "/silent", "/quiet", "/passive", "/unattend")):
        pkg_type = "unattend (.exe / Unattended Setup)"
        default_silent = "/S"
    elif any(
        a.rel_path.name.lower().endswith((".cmd", ".bat", ".ps1")) for a in inventory.artifacts
    ):
        pkg_type = "Skript-basiert (.cmd / .bat / .ps1)"
        default_silent = "/silent"
    elif (inventory.regs or inventory.nirs) and not inventory.media:
        pkg_type = "Konfiguration (Registry & Dateien)"
        default_silent = "N/A (keine externe Setup-Datei)"
    elif any(a.rel_path.name.lower().endswith(".exe") for a in inventory.media):
        pkg_type = "unattend (.exe / Setup)"
        default_silent = "/S"
    else:
        pkg_type = "Empirum Standard-Paket"
        default_silent = "/S"

    return pkg_type, default_silent


def _describe_inf_charset(charset: str) -> str:
    """Human-readable label for the Setup.inf charset actually used by the builder."""
    if charset in ("utf-8", "utf-8-sig"):
        return "UTF-8 (mit BOM)"
    if charset == "cp1252":
        return "Windows-1252 (CP1252 / ANSI)"
    if charset in ("utf-16", "utf-16-le", "utf-16-be"):
        return "UTF-16"
    return charset


def extract_manual_info(
    inventory: PackageInventory,
    inf_content: str = "",
    product_name: str | None = None,
    version: str | None = None,
    manufacturer: str | None = None,
    pkg_ir: IrPackage | None = None,
    transform_result: TransformResult | None = None,
    timestamp: datetime | None = None,
    inf_charset: str = "utf-8",
) -> PackageManualInfo:
    meta_name, meta_ver, meta_mfg, meta_desc, meta_comment = _extract_package_metadata(inventory)

    pkg_desc = (pkg_ir.description if pkg_ir and pkg_ir.description else None) or meta_desc
    pkg_comment = (
        pkg_ir.revision_comment if pkg_ir and pkg_ir.revision_comment else None
    ) or meta_comment

    final_prod = (
        product_name
        or meta_name
        or (pkg_ir.name if pkg_ir else None)
        or inventory.root_path.name
        or "Softwarepaket"
    )
    final_ver = version or meta_ver or (pkg_ir.version if pkg_ir else None) or "1.0"
    if manufacturer and manufacturer != "Matrix42":
        final_mfg = manufacturer
    else:
        final_mfg = (
            meta_mfg
            or (pkg_ir.manufacturer if pkg_ir and pkg_ir.manufacturer != "Matrix42" else None)
            or manufacturer
            or "Matrix42"
        )
    conv_time = timestamp or datetime.now()

    commands, parsed_silent = _extract_commands_and_switches(inventory, inf_content)
    pkg_type, default_silent = _detect_package_type(inventory, inf_content, commands)
    final_silent = parsed_silent if parsed_silent else default_silent

    # Determine target directory and reboot mode from inf_content
    target_dir_str = "%ProgramFiles%\\" + final_prod
    if "%ProgramFiles%" in inf_content:
        # Try to find specific path
        match = re.search(r'%ProgramFiles%\\[^"\'\r\n\t]+', inf_content)
        if match:
            target_dir_str = match.group(0).strip()
    elif "%App%" in inf_content:
        target_dir_str = "%App%"

    # Read main script content if present
    main_script_path = inventory.main_script.absolute_path if inventory.main_script else None
    script_text_lower = ""
    if main_script_path and main_script_path.exists():
        try:
            script_text_lower = main_script_path.read_text(
                encoding="latin-1", errors="replace"
            ).lower()
        except Exception:
            pass

    # Reboot detection
    reboot_needed = bool(
        re.search(
            r"\b(reboot\s*=\s*[1-9]|setreboot\s+[1-9]|rebootcomputer)\b",
            inf_content.lower(),
        )
        or "rebootcomputer" in script_text_lower
    )
    reboot_str = (
        "Systemneustart erforderlich (Reboot=1)"
        if reboot_needed
        else "Kein Neustart erforderlich (Reboot=0)"
    )

    # Architecture detection
    is_x64 = bool(
        "x64" in inf_content.lower()
        or "isrunningonx64" in inf_content.lower()
        or "isrunningonx64" in script_text_lower
    )
    platform_str = "x64 (64-Bit)" if is_x64 else "x86 / x64 (Universal)"

    # Basic parameters dictionary
    basic_params: dict[str, str] = {
        "Produktname": final_prod,
        "Hersteller": final_mfg,
        "Paketversion": final_ver,
        "Paket-Typ": pkg_type,
        "Silent-Installationsparameter": final_silent,
        "Installations-Kontext": "Maschine (Computer)",
        "Installations-Zielpfad": target_dir_str,
        "Neustart-Verhalten": reboot_str,
        "Unterstützte Plattform": platform_str,
        "Setup.inf Skriptpfad": "Install\\Setup.inf",
        "Payload-Verzeichnis": "Files\\",
        "Zeichensatz (Setup.inf)": _describe_inf_charset(inf_charset),
    }
    if pkg_desc:
        basic_params["Beschreibung"] = pkg_desc
    if pkg_comment:
        basic_params["Freigabe-Hinweis"] = pkg_comment

    # Description synthesis
    desc_paragraphs: list[str] = []
    if pkg_desc:
        desc_paragraphs.append(pkg_desc.strip())
    if pkg_comment and pkg_comment != pkg_desc:
        desc_paragraphs.append(f"Freigabe-Hinweis / Kommentar: {pkg_comment.strip()}")

    desc_paragraphs.append(
        f"Dieses Softwarepaket '{final_prod}' (Version {final_ver}) "
        f"des Herstellers '{final_mfg}' wurde automatisiert aus einem "
        f"Ivanti DSM eScript-Paket nach Matrix42 Empirum konvertiert. "
        f"Die Bereitstellung erfolgt als {pkg_type} unter Einsatz "
        f"des Silent-Parameters '{final_silent}'."
    )

    if inventory.media:
        valid_media = [
            a for a in inventory.media if not a.rel_path.name.lower().endswith("_ni5.zip")
        ]
        desc_paragraphs.append(
            f"Das Paket enthält {len(valid_media)} Payload-Datei(en) im Verzeichnis 'Files/'."
        )

    if inventory.nirs or inventory.regs:
        desc_paragraphs.append(
            f"Zur Konfiguration des Programms werden Registry-Definitionen aus "
            f"{len(inventory.nirs + inventory.regs)} Datei(en) eingespielt."
        )

    full_description = "\n\n".join(desc_paragraphs)

    # Payload file list (name, size, sha256)
    payload_files: list[tuple[str, int, str]] = []
    for art in inventory.media:
        if art.rel_path.name.lower().endswith("_ni5.zip"):
            continue
        parts_lower = [p.lower() for p in art.rel_path.parts]
        if "extern$" in parts_lower:
            idx = parts_lower.index("extern$")
            rel_name = "\\".join(art.rel_path.parts[idx + 1 :])
        else:
            rel_name = art.rel_path.name
        payload_files.append((rel_name, art.size_bytes, art.sha256 or ""))

    return PackageManualInfo(
        package_name=final_prod,
        product_name=final_prod,
        manufacturer=final_mfg,
        version=final_ver,
        conversion_timestamp=conv_time,
        package_type=pkg_type,
        silent_parameters=final_silent,
        description=full_description,
        basic_parameters=basic_params,
        payload_files=payload_files,
        command_lines=commands,
    )
