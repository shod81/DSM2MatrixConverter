"""Main QWizard implementation coordinating 5 migration steps (Task T-050).

Conforms to Chapter 5.1:
- 5-Schritte-Wizard (Auswaehlen -> Scannen -> Mapping -> Diff/Pruefung -> Export)
"""

from __future__ import annotations

from PySide6.QtWidgets import QWizard

from dsm2emp.gui.models import WizardState
from dsm2emp.gui.theme import DARK_STYLE
from dsm2emp.gui.wizard.step1_select import SelectPage
from dsm2emp.gui.wizard.step2_scan import ScanPage
from dsm2emp.gui.wizard.step3_mapping import MappingPage
from dsm2emp.gui.wizard.step4_diff import DiffPage
from dsm2emp.gui.wizard.step5_export import ExportPage


class MigrationWizard(QWizard):
    """5-Step Migration Wizard for single package conversion."""

    def __init__(self, state: WizardState | None = None) -> None:
        super().__init__()
        self.state = state or WizardState()

        self.setWindowTitle("DSM2Empirum – Paket-Migrations-Assistent")
        self.setStyleSheet(DARK_STYLE)
        self.resize(950, 680)

        # Configure Wizard Appearance
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.IndependentPages, False)

        # Add pages in order
        self.page_select = SelectPage(self.state)
        self.page_scan = ScanPage(self.state)
        self.page_mapping = MappingPage(self.state)
        self.page_diff = DiffPage(self.state)
        self.page_export = ExportPage(self.state)

        self.addPage(self.page_select)
        self.addPage(self.page_scan)
        self.addPage(self.page_mapping)
        self.addPage(self.page_diff)
        self.addPage(self.page_export)
