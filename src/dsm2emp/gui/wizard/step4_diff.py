"""Step 4: Diff, Setup.inf inspection, and validation issues (Task T-050).

Conforms to Chapter 5.1:
- Erzeugte Setup.inf Anzeige
- Validator-Ergebnisse als klickbare Liste
- TODO-Liste mit Handlungsempfehlungen
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizardPage,
)

from dsm2emp.emitter import emit
from dsm2emp.gui.highlighter import SetupInfHighlighter
from dsm2emp.gui.models import WizardState


class DiffPage(QWizardPage):
    """Step 4: Inspection, Diff & Validation Page."""

    def __init__(self, state: WizardState, parent: QWizardPage | None = None) -> None:
        super().__init__(parent)
        self.state = state

        self.setTitle("Schritt 4: Setup.inf Pruefung & Validierung")
        self.setSubTitle(
            "Ueberpruefen Sie den generierten Setup.inf-Code und die Diagnosemeldungen."
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        splitter = QSplitter()
        layout.addWidget(splitter)

        # Left side: Setup.inf viewer
        setup_inf_box = QVBoxLayout()
        header_bar = QHBoxLayout()
        lbl_code = QLabel("Generierte Setup.inf:")
        lbl_code.setObjectName("titleLabel")
        header_bar.addWidget(lbl_code)
        header_bar.addStretch()

        self.copy_btn = QPushButton("In Zwischenablage kopieren")
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        header_bar.addWidget(self.copy_btn)
        setup_inf_box.addLayout(header_bar)

        self.code_edit = QPlainTextEdit()
        self.code_edit.setReadOnly(True)
        # Modern monospace font
        mono_font = QFont("Consolas", 10)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        self.code_edit.setFont(mono_font)
        # Attach syntax highlighter
        self.highlighter = SetupInfHighlighter(self.code_edit.document())
        setup_inf_box.addWidget(self.code_edit)

        # Right side: Issues & TODOs
        right_box = QVBoxLayout()

        lbl_issues = QLabel("Validierungsergebnisse (Issues):")
        lbl_issues.setObjectName("titleLabel")
        self.issues_table = QTableWidget()
        self.issues_table.setColumnCount(4)
        self.issues_table.setHorizontalHeaderLabels(["Schwere", "Code", "Meldung", "Feld"])
        self.issues_table.setColumnWidth(0, 80)
        self.issues_table.setColumnWidth(1, 70)
        self.issues_table.setColumnWidth(2, 220)
        self.issues_table.itemClicked.connect(self._on_issue_clicked)

        lbl_todos = QLabel("Offene Punkte (TODOs):")
        lbl_todos.setObjectName("titleLabel")
        self.todos_table = QTableWidget()
        self.todos_table.setColumnCount(3)
        self.todos_table.setHorizontalHeaderLabels(["Zeile", "Befehl", "Hinweis / Meldung"])
        self.todos_table.setColumnWidth(0, 60)
        self.todos_table.setColumnWidth(1, 140)
        self.todos_table.setColumnWidth(2, 220)

        right_box.addWidget(lbl_issues)
        right_box.addWidget(self.issues_table)
        right_box.addWidget(lbl_todos)
        right_box.addWidget(self.todos_table)

        # Assemble in splitter
        from PySide6.QtWidgets import QWidget

        w_left = QWidget()
        w_left.setLayout(setup_inf_box)
        w_right = QWidget()
        w_right.setLayout(right_box)

        splitter.addWidget(w_left)
        splitter.addWidget(w_right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

    def initializePage(self) -> None:
        """Populate code editor, issues, and todos from migration result."""
        res = self.state.migration_result
        if not res:
            return

        # Emit Setup.inf text from AST if not yet stringified
        if res.transform_result and res.transform_result.document:
            inf_text, _ = emit(res.transform_result.document)
            self.state.generated_setup_inf = inf_text
            self.code_edit.setPlainText(inf_text)

        # Issues
        self.issues_table.setRowCount(len(res.issues))
        for i, iss in enumerate(res.issues):
            sev_item = QTableWidgetItem(iss.severity.upper())
            if iss.severity == "error":
                sev_item.setForeground(QColor("#ef4444"))
            elif iss.severity == "warning":
                sev_item.setForeground(QColor("#eab308"))
            else:
                sev_item.setForeground(QColor("#38bdf8"))

            code_item = QTableWidgetItem(iss.code)
            msg_item = QTableWidgetItem(iss.message)
            field_item = QTableWidgetItem(iss.field or "-")

            self.issues_table.setItem(i, 0, sev_item)
            self.issues_table.setItem(i, 1, code_item)
            self.issues_table.setItem(i, 2, msg_item)
            self.issues_table.setItem(i, 3, field_item)

        # TODOs
        todos = res.transform_result.todos if res.transform_result else []
        self.todos_table.setRowCount(len(todos))
        for j, td in enumerate(todos):
            ln = f"Z.{td.src.line}" if td.src else "-"
            ln_item = QTableWidgetItem(ln)
            raw_item = QTableWidgetItem(td.raw)
            msg_item = QTableWidgetItem(td.message)

            self.todos_table.setItem(j, 0, ln_item)
            self.todos_table.setItem(j, 1, raw_item)
            self.todos_table.setItem(j, 2, msg_item)

    def _on_issue_clicked(self, item: QTableWidgetItem) -> None:
        """Search text in Setup.inf viewer if issue mentions a field or token."""
        row = item.row()
        field_item = self.issues_table.item(row, 3)
        if field_item and field_item.text() != "-":
            term = field_item.text()
            cursor = self.code_edit.document().find(term)
            if not cursor.isNull():
                self.code_edit.setTextCursor(cursor)
                self.code_edit.centerCursor()

    def _copy_to_clipboard(self) -> None:
        """Copy generated Setup.inf text to system clipboard with temporary button feedback."""
        text = self.code_edit.toPlainText()
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            self.copy_btn.setText("Kopiert! ✓")
            QTimer.singleShot(2000, lambda: self.copy_btn.setText("In Zwischenablage kopieren"))

    def isComplete(self) -> bool:
        return True
