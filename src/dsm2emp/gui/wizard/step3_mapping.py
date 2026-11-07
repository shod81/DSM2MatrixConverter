"""Step 3: Two-column preview and construct mapping (Task T-050).

Conforms to Chapter 5.1:
- Zweispaltige Ansicht: links DSM-Skriptzeilen, rechts geplante Empirum-Konstrukte
- Konfidenz-Badge (Gruen/Gelb/Rot/TODO) und Regel-ID je Zeile
- Filter "Nur Probleme anzeigen"
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizardPage,
)

from dsm2emp.gui.models import WizardState
from dsm2emp.gui.workers import MigrationWorker
from dsm2emp.orchestrator import MigrationResult


class MappingPage(QWizardPage):
    """Step 3: Construct Mapping & Preview Page."""

    def __init__(self, state: WizardState, parent: QWizardPage | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._worker: MigrationWorker | None = None

        self.setTitle("Schritt 3: Vorschau und Konstrukt-Mapping")
        self.setSubTitle("Gegenueberstellung von DSM-Quelle und geplanten Empirum-Konstrukten.")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("Fuehre regelbasierte Transformation aus...")
        layout.addWidget(self.status_lbl)

        # Filter bar
        top_bar = QHBoxLayout()
        self.filter_issues_cb = QCheckBox("Nur Probleme / niedrige Konfidenz anzeigen")
        self.filter_issues_cb.toggled.connect(self._apply_filter)
        top_bar.addWidget(self.filter_issues_cb)
        top_bar.addStretch()
        self.summary_badge = QLabel("Konfidenz Ø: -")
        top_bar.addWidget(self.summary_badge)
        layout.addLayout(top_bar)

        # Mapping Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                "DSM-Quelle (Zeile: Befehl)",
                "Empirum-Zielkonstrukt",
                "Regel-ID",
                "Konfidenz",
                "Referenz",
            ]
        )
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 320)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 120)
        self.table.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.table)

        # Rule detail inspection box
        self.detail_box = QLabel(
            "Waehlen Sie einen Befehl aus der Tabelle, um Regel- und Mappingdetails anzuzeigen."
        )
        self.detail_box.setObjectName("infoBox")
        self.detail_box.setWordWrap(True)
        layout.addWidget(self.detail_box)

    def initializePage(self) -> None:
        """Trigger migration engine in worker thread."""
        if self.state.migration_result is not None:
            self.progress_bar.setVisible(False)
            self.status_lbl.setText("Transformation erfolgreich durchgefuehrt.")
            self._render_mapping(self.state.migration_result)
            return

        if not self.state.source_dir:
            return

        self.progress_bar.setVisible(True)
        self.status_lbl.setText("Transformiere eScript in Empirum-AST...")

        self._worker = MigrationWorker(
            source_dir=self.state.source_dir,
            target_dir=self.state.target_dir,
            options=self.state.options,
        )
        self._worker.finished_result.connect(self._on_migration_done)
        self._worker.failed.connect(self._on_migration_failed)
        self._worker.start()

    def _on_migration_done(self, result: MigrationResult) -> None:
        self.state.migration_result = result
        self.progress_bar.setVisible(False)
        self.status_lbl.setText("Transformation erfolgreich durchgefuehrt.")
        self._render_mapping(result)
        self.completeChanged.emit()

    def _on_migration_failed(self, error: str) -> None:
        self.progress_bar.setVisible(False)
        self.status_lbl.setText(f"Transformationsfehler: {error}")
        self.completeChanged.emit()

    def _render_mapping(self, result: MigrationResult) -> None:
        from dsm2emp.report.kpi import calculate_kpis
        from dsm2emp.rules.model import unrepresented_todos

        kpis = calculate_kpis(result)
        conf_pct = int(kpis.average_confidence * 100)
        color_hex = (
            "#22c55e"
            if kpis.confidence_color == "green"
            else ("#eab308" if kpis.confidence_color == "yellow" else "#ef4444")
        )
        badge_text = (
            f"Konfidenz Ø: {conf_pct}% "
            f"(Ampel: {kpis.confidence_color.upper()}) · {kpis.todo_count} TODOs"
        )
        self.summary_badge.setText(badge_text)
        self.summary_badge.setStyleSheet(f"color: {color_hex}; font-weight: bold; font-size: 13px;")

        self.table.setRowCount(0)
        traces = result.transform_result.traces if result.transform_result else []
        todos = result.transform_result.todos if result.transform_result else []

        # Only show todos that have no trace row of their own (transformation
        # TODOs already appear in the trace list with confidence "todo")
        extra_todos = unrepresented_todos(traces, todos)

        all_rows = []
        for t in traces:
            src = f"Z.{t.source_line}: {t.source_raw}" if t.source_line else t.source_raw
            all_rows.append(
                {
                    "src": src,
                    "target": t.target_summary,
                    "rule": t.rule_id,
                    "confidence": t.confidence,
                    "ref": t.doc_ref,
                    "is_problem": t.confidence in ("low", "todo"),
                }
            )

        for td in extra_todos:
            src = f"Z.{td.src.line}: {td.raw}" if td.src else td.raw
            all_rows.append(
                {
                    "src": src,
                    "target": f"TODO: {td.message}",
                    "rule": "TODO",
                    "confidence": "todo",
                    "ref": "Manuelle Pruefung",
                    "is_problem": True,
                }
            )

        self._all_rows = all_rows
        self._populate_table(all_rows)

    def _apply_filter(self, only_problems: bool) -> None:
        if not hasattr(self, "_all_rows"):
            return
        if only_problems:
            rows = [r for r in self._all_rows if r["is_problem"]]
        else:
            rows = self._all_rows
        self._populate_table(rows)

    def _populate_table(self, rows: list[dict[str, object]]) -> None:
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            src_item = QTableWidgetItem(str(row["src"]))
            tgt_item = QTableWidgetItem(str(row["target"]))
            rule_item = QTableWidgetItem(str(row["rule"]))
            conf_str = str(row["confidence"])
            conf_item = QTableWidgetItem(conf_str.upper())
            ref_item = QTableWidgetItem(str(row["ref"]))

            # Color coding per Chapter 5.1
            if conf_str == "high":
                conf_item.setForeground(QColor("#22c55e"))
            elif conf_str == "medium":
                conf_item.setForeground(QColor("#eab308"))
            elif conf_str == "low":
                conf_item.setForeground(QColor("#f97316"))
            else:
                conf_item.setForeground(QColor("#ef4444"))

            self.table.setItem(i, 0, src_item)
            self.table.setItem(i, 1, tgt_item)
            self.table.setItem(i, 2, rule_item)
            self.table.setItem(i, 3, conf_item)
            self.table.setItem(i, 4, ref_item)

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        """Show full details of the clicked row in the detail box."""
        row = item.row()
        cells = [self.table.item(row, col) for col in range(5)]
        src = cells[0].text() if cells[0] else "-"
        tgt = cells[1].text() if cells[1] else "-"
        rule = cells[2].text() if cells[2] else "-"
        conf = cells[3].text() if cells[3] else "-"
        ref = cells[4].text() if cells[4] else "-"

        self.detail_box.setText(
            f"Regel: {rule} | Konfidenz: {conf} | Doku-Referenz: {ref}\nDSM: {src}\nEmpirum: {tgt}"
        )

    def isComplete(self) -> bool:
        return self.state.migration_result is not None
