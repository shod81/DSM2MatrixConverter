"""Data models for Empirum software package manual documentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class PackageManualInfo:
    """Structured information for generating the package manual PDF.

    Captures package metadata, basic parameters, installer classification,
    silent arguments, conversion timestamp, and descriptive summaries.
    """

    package_name: str
    product_name: str
    manufacturer: str
    version: str
    conversion_timestamp: datetime
    package_type: str  # e.g. ".msi (Windows Installer)", "unattend (.exe / Inno Setup)"
    silent_parameters: str  # e.g. "/qn TRANSFORMS=\"setup.mst\""
    description: str  # Kurzbeschreibung des Pakets
    basic_parameters: dict[str, str] = field(default_factory=dict)  # Basisparameter
    payload_files: list[tuple[str, int, str]] = field(default_factory=list)  # (name, size, sha)
    command_lines: list[str] = field(default_factory=list)  # Install/uninstall commands
