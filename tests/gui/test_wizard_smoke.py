"""Smoke tests for MigrationWizard (Task T-050)."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from dsm2emp.fixtures.make_packages import create_p01_pure_msi
from dsm2emp.gui.models import WizardState
from dsm2emp.gui.wizard.wizard import MigrationWizard
from dsm2emp.orchestrator import MigrationOptions, migrate_single
from dsm2emp.scanner.scanner import scan


def test_wizard_initialization(qtbot: QtBot) -> None:
    """Wizard creates all 5 pages cleanly."""
    wizard = MigrationWizard()
    qtbot.addWidget(wizard)

    assert len(wizard.pageIds()) == 5
    assert wizard.page_select is not None
    assert wizard.page_scan is not None
    assert wizard.page_mapping is not None
    assert wizard.page_diff is not None
    assert wizard.page_export is not None


def test_wizard_step1_validation(qtbot: QtBot, tmp_path: Path) -> None:
    """Step 1 is only complete when a valid source directory is provided."""
    wizard = MigrationWizard()
    qtbot.addWidget(wizard)

    # Initially empty -> incomplete
    assert not wizard.page_select.isComplete()

    # Invalid path -> incomplete
    wizard.page_select.src_edit.setText(str(tmp_path / "non_existing_pkg"))
    assert not wizard.page_select.isComplete()

    # Valid directory -> complete
    valid_dir = tmp_path / "valid_pkg"
    valid_dir.mkdir()
    wizard.page_select.src_edit.setText(str(valid_dir))
    assert wizard.page_select.isComplete()


def test_wizard_pages_render_domain_data(qtbot: QtBot, tmp_path: Path) -> None:
    """All 5 wizard pages initialize and render without errors given domain data."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    res = migrate_single(src, tgt, MigrationOptions(force=True))
    inventory = scan(src)

    state = WizardState(
        source_dir=src,
        target_dir=tgt,
        inventory=inventory,
        migration_result=res,
    )

    wizard = MigrationWizard(state)
    qtbot.addWidget(wizard)

    # Test Step 2 Scan render
    wizard.page_scan.initializePage()
    assert wizard.page_scan.tree.topLevelItemCount() > 0

    # Test Step 3 Mapping render
    wizard.page_mapping.initializePage()
    assert wizard.page_mapping.table.rowCount() > 0
    assert wizard.page_mapping.detail_box is not None

    # Test Step 4 Diff & Issues render
    wizard.page_diff.initializePage()
    assert len(wizard.page_diff.code_edit.toPlainText()) > 0
    assert wizard.page_diff.highlighter is not None
    assert wizard.page_diff.copy_btn is not None

    # Test Step 5 Export setup
    wizard.page_export.initializePage()
    assert wizard.page_export.tgt_edit.text() != ""
    assert wizard.page_export.open_explorer_btn is not None
