"""Parser for Ivanti DSM _ExpInfo.xml metadata export files."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from dsm2emp.io.encoding import read_text

# Generic DSM organizational containers in LDAP ObjectLocation to ignore as manufacturer
GENERIC_LDAP_CONTAINERS = {
    "freeware",
    "licenseware",
    "application library",
    "global software library",
    "applications",
    "software",
    "standard",
    "sw-verteilung",
    "softwarepakete",
    "enterprise",
}


@dataclass(frozen=True)
class ExpInfoMetadata:
    """Extracted package metadata from DSM _ExpInfo.xml."""

    name: str | None = None
    description: str | None = None
    manufacturer: str | None = None
    version: str | None = None
    revision: str | None = None
    revision_comment: str | None = None
    release_date: str | None = None


def _extract_version_from_name(name: str) -> str | None:
    """Extract version component from package name string if present."""
    # Match patterns like "7Zip_25.01", "Zoom 7.1.43453", "B_Adobe_Reader_DC 26.002.21900"
    match = re.search(r"(?:[ _vV]|^)(\d+(?:\.\d+)+[a-zA-Z0-9_\-]*)", name)
    if match:
        return match.group(1).strip()
    return None


def _extract_manufacturer_from_location(location: str) -> str | None:
    """Extract manufacturer name from DSM LDAP ObjectLocation attribute."""
    # Example: <LDAP://o=7Zip_25.01,DC=7Zip,DC=Freeware,DC=Application Library,...>
    dcs = re.findall(r"DC=([^,>]+)", location, flags=re.IGNORECASE)
    for dc in dcs:
        clean_dc: str = dc.strip()
        if clean_dc.lower() not in GENERIC_LDAP_CONTAINERS:
            return clean_dc
    return None


def parse_expinfo_xml(path: Path) -> ExpInfoMetadata:
    """Parse DSM _ExpInfo.xml and extract rich package metadata."""
    if not path.exists():
        return ExpInfoMetadata()

    try:
        content, _ = read_text(path)
        if not content.strip():
            return ExpInfoMetadata()
        root = ET.fromstring(content)
    except Exception:
        return ExpInfoMetadata()

    # Find relevant MdsObjects. eScriptPackage objects hold the software revisions
    all_objs = list(root.iter("MdsObject"))
    escript_objs = [
        o for o in all_objs if (o.findtext("SchemaTag") or "").lower() == "escriptpackage"
    ]
    target_objs = escript_objs if escript_objs else all_objs
    if not target_objs:
        return ExpInfoMetadata()

    # Search for the latest revision (IsLastRevision=1) or take the last object
    selected_obj = target_objs[-1]
    for obj in target_objs:
        for prop in obj.iter("MdsProperty"):
            tag = prop.findtext("Tag") or ""
            val = prop.findtext("Value") or ""
            if tag.lower() == "islastrevision" and val == "1":
                selected_obj = obj
                break

    # Extract Name & Description from MdsObject tags
    raw_name = (selected_obj.findtext("Name") or "").strip()
    raw_desc = (selected_obj.findtext("Description") or "").strip()
    raw_loc = (selected_obj.findtext("ObjectLocation") or "").strip()

    # Extract properties from MdsPropGroup / MdsProperty
    props: dict[str, str] = {}
    for prop in selected_obj.iter("MdsProperty"):
        prop_tag = prop.findtext("Tag")
        prop_val = prop.findtext("Value")
        if prop_tag and prop_val:
            props[prop_tag.strip()] = prop_val.strip()

    # Fallback / property enrichment
    display_name = props.get("DisplayName", "")
    final_name = raw_name or display_name or None

    final_desc = raw_desc or props.get("Description", "") or None
    rev_comment = props.get("SwRevisionComment", "") or None
    release_date = props.get("ReleaseDate", "") or None
    revision = props.get("SoftwareRevision", "") or None

    # Manufacturer from LDAP location or tags
    manufacturer = _extract_manufacturer_from_location(raw_loc)

    # Version from name pattern or properties
    version = _extract_version_from_name(final_name) if final_name else None

    return ExpInfoMetadata(
        name=final_name,
        description=final_desc,
        manufacturer=manufacturer,
        version=version,
        revision=revision,
        revision_comment=rev_comment,
        release_date=release_date,
    )
