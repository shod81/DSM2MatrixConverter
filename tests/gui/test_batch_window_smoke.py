"""Smoke tests for BatchWindow (Task T-050)."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from dsm2emp.fixtures.make_packages import create_p01_pure_msi
from dsm2emp.gui.batch_window import BatchWindow
from dsm2emp.orchestrator import MigrationOptions, migrate_single


def test_batch_window_initialization(qtbot: QtBot) -> None:
    """BatchWindow initializes with all expected widgets."""
    win = BatchWindow()
    qtbot.addWidget(win)

    assert win.table.columnCount() == 5
    assert win.jobs_spin.value() >= 1
    assert win.resume_cb.isChecked()
    assert win.start_btn.isEnabled()


def test_batch_window_package_completion_updates_ui(qtbot: QtBot, tmp_path: Path) -> None:
    """BatchWindow updates table rows when package completes."""
    win = BatchWindow()
    qtbot.addWidget(win)

    src = create_p01_pure_msi(tmp_path / "pkg1")
    tgt = tmp_path / "pkg1_out"
    res = migrate_single(src, tgt, MigrationOptions(force=True))

    # Set up a test package in table
    win.table.setRowCount(1)
    from PySide6.QtWidgets import QTableWidgetItem

    win.table.setItem(0, 0, QTableWidgetItem(src.name))
    win.table.setItem(0, 1, QTableWidgetItem("Warteschlange"))

    # Simulate completed package result signal
    win._on_package_completed(res)

    # Verify table updated
    status_item = win.table.item(0, 1)
    assert status_item is not None
    assert status_item.text() in ("OK", "WARNINGS")

    conf_item = win.table.item(0, 2)
    assert conf_item is not None
    assert conf_item.text().endswith("%")


def test_batch_window_filter_and_search(qtbot: QtBot) -> None:
    """BatchWindow search edit and combo filter rows correctly."""
    win = BatchWindow()
    qtbot.addWidget(win)

    from PySide6.QtWidgets import QTableWidgetItem

    win.table.setRowCount(2)
    win.table.setItem(0, 0, QTableWidgetItem("Chrome_129"))
    win.table.setItem(0, 1, QTableWidgetItem("OK"))
    win.table.setItem(1, 0, QTableWidgetItem("Legacy_App"))
    win.table.setItem(1, 1, QTableWidgetItem("WARNINGS"))

    # Filter by name
    win.search_edit.setText("Chrome")
    assert not win.table.isRowHidden(0)
    assert win.table.isRowHidden(1)

    win.search_edit.setText("")
    assert not win.table.isRowHidden(0)
    assert not win.table.isRowHidden(1)

    # Filter by status combo
    idx_issues = win.status_filter_combo.findData("issues")
    win.status_filter_combo.setCurrentIndex(idx_issues)
    assert win.table.isRowHidden(0)
    assert not win.table.isRowHidden(1)
