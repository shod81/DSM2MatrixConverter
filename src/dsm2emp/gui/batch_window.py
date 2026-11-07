"""Batch Migration Window (Task T-050).

Conforms to Chapter 5.1:
- Tabelle Paketname · Status · Konfidenz-Ø · TODO-Anzahl · Dauer
- Kontextmenue: "Report oeffnen", "Nur dieses erneut migrieren"
- Fortschrittsbalken gesamt
- Nach Abschluss Sammelreport-Button
- Worker-Thread (BatchWorker), UI friert nie ein
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dsm2emp.batch import BatchOptions, BatchResult, discover_packages
from dsm2emp.gui.theme import DARK_STYLE
from dsm2emp.gui.workers import BatchWorker, MigrationWorker
from dsm2emp.orchestrator import MigrationOptions, MigrationResult
from dsm2emp.report.kpi import calculate_kpis


class BatchWindow(QMainWindow):
    """Batch Migration Dashboard Window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DSM2Empirum – Batch-Migration")
        self.setStyleSheet(DARK_STYLE)
        self.resize(1050, 720)

        self._worker: BatchWorker | None = None
        self._single_worker: MigrationWorker | None = None
        self._results_by_name: dict[str, MigrationResult] = {}
        self._batch_summary: BatchResult | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)

        # Title
        title_lbl = QLabel("Batch-Paketmigration")
        title_lbl.setObjectName("titleLabel")
        layout.addWidget(title_lbl)

        # Config Bar
        config_layout = QHBoxLayout()
        config_layout.setSpacing(10)

        self.src_btn = QPushButton("Quellverzeichnis...")
        self.src_btn.clicked.connect(self._browse_src)
        self.src_lbl = QLabel("Keine Quelle gewaehlt")
        self.src_lbl.setObjectName("infoBox")

        self.tgt_btn = QPushButton("Zielverzeichnis...")
        self.tgt_btn.clicked.connect(self._browse_tgt)
        self.tgt_lbl = QLabel("Kein Ziel gewaehlt")
        self.tgt_lbl.setObjectName("infoBox")

        config_layout.addWidget(self.src_btn)
        config_layout.addWidget(self.src_lbl, 1)
        config_layout.addWidget(self.tgt_btn)
        config_layout.addWidget(self.tgt_lbl, 1)
        layout.addLayout(config_layout)

        # Controls Bar
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(16)

        ctrl_layout.addWidget(QLabel("Parallele Jobs:"))
        self.jobs_spin = QSpinBox()
        self.jobs_spin.setRange(1, 16)
        self.jobs_spin.setValue(4)
        ctrl_layout.addWidget(self.jobs_spin)

        self.resume_cb = QCheckBox("Wiederaufnahme (--resume)")
        self.resume_cb.setChecked(True)
        ctrl_layout.addWidget(self.resume_cb)

        ctrl_layout.addStretch()

        self.start_btn = QPushButton("Batch-Migration starten")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self._start_batch)
        ctrl_layout.addWidget(self.start_btn)
        layout.addLayout(ctrl_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Filter Bar
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Paketname suchen...")
        self.search_edit.textChanged.connect(self._apply_table_filter)
        filter_layout.addWidget(self.search_edit, 1)

        self.status_filter_combo = QComboBox()
        self.status_filter_combo.addItem("Alle Status", "all")
        self.status_filter_combo.addItem("Nur OK", "ok")
        self.status_filter_combo.addItem("Nur mit Warnungen / Fehlern", "issues")
        self.status_filter_combo.currentIndexChanged.connect(self._apply_table_filter)
        filter_layout.addWidget(self.status_filter_combo)
        layout.addLayout(filter_layout)

        # Main Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                "Paketname",
                "Status",
                "Konfidenz Ø",
                "TODOs",
                "Dauer",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 90)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table)

        # Footer Actions
        footer_layout = QHBoxLayout()
        self.status_footer = QLabel("Bereit.")
        footer_layout.addWidget(self.status_footer)
        footer_layout.addStretch()

        self.open_summary_btn = QPushButton("Sammelreport oeffnen")
        self.open_summary_btn.setEnabled(False)
        self.open_summary_btn.clicked.connect(self._open_summary_report)
        footer_layout.addWidget(self.open_summary_btn)
        layout.addLayout(footer_layout)

        self._source_dir: Path | None = None
        self._target_dir: Path | None = None

    def _browse_src(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Batch-Quellordner mit DSM-Paketen")
        if path:
            self._source_dir = Path(path)
            self.src_lbl.setText(str(self._source_dir))

    def _browse_tgt(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Batch-Zielordner fuer Empirum")
        if path:
            self._target_dir = Path(path)
            self.tgt_lbl.setText(str(self._target_dir))

    def _start_batch(self) -> None:
        if not self._source_dir or not self._target_dir:
            self.status_footer.setText("Bitte Quell- und Zielverzeichnis auswaehlen!")
            return

        packages = discover_packages(self._source_dir)
        if not packages:
            self.status_footer.setText("Keine DSM-Pakete im Quellverzeichnis gefunden.")
            return

        self.table.setRowCount(len(packages))
        self._results_by_name.clear()

        # Disable sorting while populating: live sorting would scatter cells
        # written row-by-row across reordered rows (classic Qt pitfall)
        self.table.setSortingEnabled(False)
        for i, pkg in enumerate(packages):
            self.table.setItem(i, 0, QTableWidgetItem(pkg.name))
            self.table.setItem(i, 1, QTableWidgetItem("Warteschlange"))
            self.table.setItem(i, 2, QTableWidgetItem("-"))
            self.table.setItem(i, 3, QTableWidgetItem("-"))
            self.table.setItem(i, 4, QTableWidgetItem("-"))
        self.table.setSortingEnabled(True)

        self.progress_bar.setRange(0, len(packages))
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.status_footer.setText(f"Starte Batch fuer {len(packages)} Pakete...")

        batch_opts = BatchOptions(
            force=True,
            jobs=self.jobs_spin.value(),
            resume=self.resume_cb.isChecked(),
        )
        self._worker = BatchWorker(
            source_dir=self._source_dir,
            target_dir=self._target_dir,
            options=batch_opts,
        )
        self._worker.package_completed.connect(self._on_package_completed)
        self._worker.batch_finished.connect(self._on_batch_finished)
        self._worker.failed.connect(self._on_batch_failed)
        self._worker.start()

    def _on_package_completed(self, res: MigrationResult) -> None:
        pkg_name = res.source_root.name
        self._results_by_name[pkg_name] = res
        self.progress_bar.setValue(self.progress_bar.value() + 1)

        kpis = calculate_kpis(res)
        if res.success and res.exit_code == 0:
            status = "ok"
        elif res.exit_code == 1:
            status = "warnings"
        else:
            status = "failed"

        # Find row for package (sorting disabled while updating so the located
        # row cannot shift between the setItem calls)
        self.table.setSortingEnabled(False)
        try:
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 0)
                if item and item.text() == pkg_name:
                    status_item = QTableWidgetItem(status.upper())
                    if status == "ok":
                        status_item.setForeground(QColor("#22c55e"))
                    elif status == "warnings":
                        status_item.setForeground(QColor("#eab308"))
                    else:
                        status_item.setForeground(QColor("#ef4444"))

                    conf_item = QTableWidgetItem(f"{int(kpis.average_confidence * 100)}%")
                    todo_item = QTableWidgetItem(str(kpis.todo_count))
                    dur_item = QTableWidgetItem("fertig")

                    self.table.setItem(r, 1, status_item)
                    self.table.setItem(r, 2, conf_item)
                    self.table.setItem(r, 3, todo_item)
                    self.table.setItem(r, 4, dur_item)
                    break
        finally:
            self.table.setSortingEnabled(True)

    def _on_batch_finished(self, summary: BatchResult) -> None:
        self._batch_summary = summary
        self.start_btn.setEnabled(True)
        self.status_footer.setText(
            f"Batch abgeschlossen: {summary.total_packages} Pakete "
            f"({summary.successful} erfolgreich, {summary.warnings} mit Warnungen, "
            f"{summary.failed} Fehler)."
        )
        if self._summary_report_path() is not None:
            self.open_summary_btn.setEnabled(True)

    def _on_batch_failed(self, error: str) -> None:
        self.start_btn.setEnabled(True)
        self.status_footer.setText(f"Batch-Fehler: {error}")

    def _show_context_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        name_item = self.table.item(row, 0)
        if not name_item:
            return

        pkg_name = name_item.text()
        menu = QMenu(self)

        act_explorer = QAction("Zielordner im Explorer oeffnen", self)
        act_explorer.triggered.connect(lambda: self._open_package_folder(pkg_name))

        act_report = QAction("Report oeffnen", self)
        act_report.triggered.connect(lambda: self._open_package_report(pkg_name))

        act_remigrate = QAction("Nur dieses erneut migrieren", self)
        act_remigrate.triggered.connect(lambda: self._remigrate_single(pkg_name))

        menu.addAction(act_explorer)
        menu.addAction(act_report)
        menu.addAction(act_remigrate)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _package_target_dir(self, pkg_name: str) -> Path | None:
        """Resolve a package's target directory (uses the recorded result path,
        so nested packages like Vendor\\Product are opened correctly)."""
        res = self._results_by_name.get(pkg_name)
        if res and res.target_root:
            return res.target_root
        if self._target_dir:
            return self._target_dir / pkg_name
        return None

    def _summary_report_path(self) -> Path | None:
        """Path of the batch-level overview page (Paketindex.html, fallback report.html)."""
        if not self._target_dir:
            return None
        index_file = self._target_dir / "Paketindex.html"
        if index_file.exists():
            return index_file
        legacy_report = self._target_dir / "report.html"
        return legacy_report if legacy_report.exists() else None

    def _open_package_folder(self, pkg_name: str) -> None:
        pkg_folder = self._package_target_dir(pkg_name)
        if pkg_folder and pkg_folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(pkg_folder)))
        else:
            self.status_footer.setText(f"Ordner fuer {pkg_name} existiert noch nicht.")

    def _open_package_report(self, pkg_name: str) -> None:
        pkg_folder = self._package_target_dir(pkg_name)
        report_file = pkg_folder / "report.html" if pkg_folder else None
        if report_file and report_file.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(report_file)))
        else:
            self.status_footer.setText(f"Kein Report fuer {pkg_name} gefunden.")

    def _remigrate_single(self, pkg_name: str) -> None:
        if not self._source_dir or not self._target_dir:
            return
        if self._single_worker is not None and self._single_worker.isRunning():
            self.status_footer.setText("Es laeuft bereits eine Remigration. Bitte warten.")
            return

        # Prefer the recorded paths so nested packages (Vendor\\Product) work
        res = self._results_by_name.get(pkg_name)
        src = res.source_root if res else self._source_dir / pkg_name
        tgt = res.target_root if (res and res.target_root) else self._target_dir / pkg_name
        self.status_footer.setText(f"Migriere {pkg_name} erneut...")

        self._single_worker = MigrationWorker(src, tgt, MigrationOptions(force=True))
        self._single_worker.finished_result.connect(
            lambda _res: self.status_footer.setText(f"{pkg_name} erfolgreich remigriert.")
        )
        self._single_worker.failed.connect(
            lambda err: self.status_footer.setText(
                f"Remigration von {pkg_name} fehlgeschlagen: {err}"
            )
        )
        self._single_worker.start()

    def _open_summary_report(self) -> None:
        summary_path = self._summary_report_path()
        if summary_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(summary_path)))

    def _apply_table_filter(self) -> None:
        """Filter table rows based on search text and status dropdown."""
        search_term = self.search_edit.text().strip().lower()
        status_filter = self.status_filter_combo.currentData()

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            status_item = self.table.item(row, 1)
            name_text = name_item.text().lower() if name_item else ""
            status_text = status_item.text().upper() if status_item else ""

            matches_search = (not search_term) or (search_term in name_text)
            if status_filter == "ok":
                matches_status = status_text == "OK"
            elif status_filter == "issues":
                matches_status = status_text in ("WARNINGS", "FAILED")
            else:
                matches_status = True

            self.table.setRowHidden(row, not (matches_search and matches_status))
