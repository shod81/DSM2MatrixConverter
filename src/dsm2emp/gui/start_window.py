"""Start/Landing window presenting two migration paths (Task T-050).

Conforms to Chapter 5.1:
- Startbildschirm: zwei Pfade
  1. "Einzelnes Paket migrieren" (oeffnet 5-Schritte-Assistent / MigrationWizard)
  2. "Batch-Migration" (oeffnet BatchWindow mit Uebersichtstabelle)
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dsm2emp.gui.batch_window import BatchWindow
from dsm2emp.gui.theme import DARK_STYLE
from dsm2emp.gui.wizard.wizard import MigrationWizard


class StartWindow(QMainWindow):
    """Landing Window offering Single Package and Batch Migration paths."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DSM2Empirum – Paket-Migrationszentrum")
        self.setStyleSheet(DARK_STYLE)
        self.resize(750, 480)

        self._active_window: QWidget | None = None

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(24)

        # Header Title
        title_box = QVBoxLayout()
        title_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("DSM2Empirum Migration Center")
        title.setObjectName("titleLabel")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #38bdf8;")
        subtitle = QLabel("Deterministische Migration von Ivanti DSM nach Matrix42 Empirum")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setStyleSheet("font-size: 14px; color: #94a3b8;")
        title_box.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        title_box.addWidget(subtitle, alignment=Qt.AlignmentFlag.AlignCenter)
        main_layout.addLayout(title_box)

        # Two Path Cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(20)

        # Card 1: Single Package Wizard
        card1 = self._create_card(
            title="📦 Einzelnes Paket migrieren",
            desc=(
                "Gefuehrter 5-Schritte-Assistent mit Artefakt-Scan, AST-Mapping, "
                "Syntax-Vorschau und sofortigem Export."
            ),
            btn_text="Assistent starten",
            on_click=self._open_wizard,
        )

        # Card 2: Batch Migration
        card2 = self._create_card(
            title="⚡ Batch-Migration",
            desc=(
                "Parallele Stapelverarbeitung grosser Paketbestaende mit "
                "Status-Monitoring, Wiederaufnahme und Sammelreport."
            ),
            btn_text="Batch-Modus oeffnen",
            on_click=self._open_batch,
        )

        cards_layout.addWidget(card1)
        cards_layout.addWidget(card2)
        main_layout.addLayout(cards_layout)

        # Footer
        footer = QLabel("Offline & Quellschutz garantiert · Regelset v1.0")
        footer.setStyleSheet("color: #64748b; font-size: 11px;")
        main_layout.addWidget(footer, alignment=Qt.AlignmentFlag.AlignCenter)

    def _create_card(
        self, title: str, desc: str, btn_text: str, on_click: Callable[[], None]
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("cardFrame")
        frame.setStyleSheet(
            "QFrame#cardFrame { background-color: #1e293b; border: 1px solid #334155; "
            "border-radius: 8px; padding: 20px; } "
            "QFrame#cardFrame:hover { border: 1px solid #38bdf8; background-color: #243248; }"
        )
        layout = QVBoxLayout(frame)
        layout.setSpacing(12)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        lbl_desc = QLabel(desc)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #cbd5e1; font-size: 13px; line-height: 1.4;")

        btn = QPushButton(btn_text)
        btn.setObjectName("primaryButton")
        btn.clicked.connect(on_click)

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_desc, 1)
        layout.addWidget(btn)

        return frame

    def _open_wizard(self) -> None:
        self.wizard = MigrationWizard()
        self.wizard.show()

    def _open_batch(self) -> None:
        self.batch_window = BatchWindow()
        self.batch_window.show()
