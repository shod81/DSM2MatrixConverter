"""Step 1: Select source/target folders and migration options (Task T-050).

Conforms to Chapter 5.1:
- Quellordner (nur lesend geöffnet, Quellschutz-Hinweis eingeblendet)
- Optionaler Zielordner
- KI-Schalter (Standard AUS, ausgraut wenn kein Key) mit Klartext-Hinweis

Es gibt genau ein eingebautes Regelwerk; ein
Regelsatz-Dropdown existiert bewusst nicht. Ein externes Regelwerk lässt sich
nur über die CLI (--rules) bzw. MigrationOptions.rules_path laden.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWizardPage,
)

from dsm2emp.gui.models import WizardState


class SelectPage(QWizardPage):
    """Step 1: Package Selection and Configuration."""

    def __init__(self, state: WizardState, parent: QWizardPage | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.setAcceptDrops(True)

        self.setTitle("Schritt 1: Paket und Optionen auswaehlen")
        self.setSubTitle("Waehlen Sie das zu migrierende DSM-Paket und grundlegende Optionen.")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Quellschutz notice (FR-001)
        warning_lbl = QLabel(
            "Quellschutz aktiv: Das Quellverzeichnis wird strikt schreibgeschuetzt geoeffnet.\n"
            "Es finden keinerlei Schreiboperationen oder Skriptausfuehrungen in der Quelle statt."
        )
        warning_lbl.setObjectName("warningLabel")
        layout.addWidget(warning_lbl)

        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        # Source folder selection
        src_box = QHBoxLayout()
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText(
            "Pfad zum DSM-Paketordner (oder Ordner per Drag & Drop hierher ziehen)..."
        )
        self.src_edit.textChanged.connect(self._on_src_changed)
        src_btn = QPushButton("Durchsuchen...")
        src_btn.clicked.connect(self._browse_source)
        src_box.addWidget(self.src_edit)
        src_box.addWidget(src_btn)
        form_layout.addRow("DSM-Quellordner*:", src_box)

        # Validation status label
        self.validation_lbl = QLabel("")
        self.validation_lbl.setStyleSheet("font-size: 12px; margin-left: 4px;")
        form_layout.addRow("", self.validation_lbl)

        # Target folder selection
        tgt_box = QHBoxLayout()
        self.tgt_edit = QLineEdit()
        self.tgt_edit.setPlaceholderText(
            "Optional: Zielverzeichnis (Standard: <Quelle>_Empirum)..."
        )
        self.tgt_edit.textChanged.connect(self._on_tgt_changed)
        tgt_btn = QPushButton("Durchsuchen...")
        tgt_btn.clicked.connect(self._browse_target)
        tgt_box.addWidget(self.tgt_edit)
        tgt_box.addWidget(tgt_btn)
        form_layout.addRow("Empirum-Zielordner:", tgt_box)

        layout.addLayout(form_layout)

        # AI options section
        self.ai_checkbox = QCheckBox("Optionale KI-Unterstuetzung aktivieren")
        self.ai_checkbox.setChecked(False)
        self.ai_checkbox.setEnabled(False)  # Disabled by default until key is configured
        layout.addWidget(self.ai_checkbox)

        ai_info = QLabel(
            "Offline-Modus aktiv: Es verlassen zu keinem Zeitpunkt Daten das lokale System.\n"
            "KI-Features erfordern API-Schluessel im Windows Credential Manager."
        )
        ai_info.setObjectName("infoBox")
        layout.addWidget(ai_info)

        layout.addStretch()

    def _browse_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "DSM-Quellordner auswaehlen")
        if path:
            self.src_edit.setText(path)

    def _browse_target(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Empirum-Zielordner auswaehlen")
        if path:
            self.tgt_edit.setText(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept folder drags."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).is_dir():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle dropped folder by populating source path."""
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.is_dir():
                    self.src_edit.setText(str(p))
                    event.acceptProposedAction()
                    return

    def _on_src_changed(self, text: str) -> None:
        raw = text.strip()
        if not raw:
            self.state.source_dir = None
            self.validation_lbl.setText("")
            self.completeChanged.emit()
            return

        p = Path(raw)
        self.state.source_dir = p

        if not p.exists() or not p.is_dir():
            self.validation_lbl.setText("✗ Verzeichnis existiert nicht")
            self.validation_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
        else:
            # Check for typical DSM files
            has_script = any(p.glob("*.inc")) or any(p.glob("*.dsm")) or any(p.glob("*.nis"))
            has_reg = any(p.glob("*.nir")) or any(p.glob("*.reg"))
            has_meta = (p / "Package.ini").exists()

            if has_script or has_meta or has_reg:
                parts = []
                if has_script:
                    parts.append("Skript gefunden")
                if has_meta:
                    parts.append("Package.ini vorhanden")
                if has_reg:
                    parts.append("Registry-Artefakte")
                summary = ", ".join(parts)
                self.validation_lbl.setText(f"✓ Gültiges DSM-Paket erkannt ({summary})")
                self.validation_lbl.setStyleSheet(
                    "color: #22c55e; font-weight: bold; font-size: 12px;"
                )
            else:
                self.validation_lbl.setText(
                    "ℹ Ordner existiert (noch keine DSM-Skripte/Dateien erkannt)"
                )
                self.validation_lbl.setStyleSheet("color: #eab308; font-size: 12px;")

        self.completeChanged.emit()

    def _on_tgt_changed(self, text: str) -> None:
        p = Path(text.strip()) if text.strip() else None
        self.state.target_dir = p

    def isComplete(self) -> bool:
        """Page is complete when source path is specified and exists."""
        if not self.state.source_dir:
            return False
        return self.state.source_dir.is_dir()
