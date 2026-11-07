"""State models for GUI wizards and windows (Task T-050)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dsm2emp.builder.builder import BuildResult
from dsm2emp.orchestrator import MigrationOptions, MigrationResult
from dsm2emp.scanner.inventory import PackageInventory


@dataclass
class WizardState:
    """Carries migration state between wizard steps 1 to 5.

    Conforms to Chapter 5.1: Views only read domain result objects.
    """

    source_dir: Path | None = None
    target_dir: Path | None = None
    options: MigrationOptions = field(default_factory=MigrationOptions)
    inventory: PackageInventory | None = None
    migration_result: MigrationResult | None = None
    build_result: BuildResult | None = None
    generated_setup_inf: str | None = None
