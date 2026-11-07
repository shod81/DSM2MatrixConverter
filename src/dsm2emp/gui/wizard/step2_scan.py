"""Step 2: Package scan and artifact inventory (Task T-050).

Conforms to Chapter 5.1:
- Fortschrittsliste der Artefakte (Baumansicht: Skripte/Registry/Medien/unbekannt)
- Encoding-Badges und Groessenangaben
- Zaehler der Artefakte und Tree-Hash
- Asynchron via ScanWorker, friert nie ein
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWizardPage,
)

from dsm2emp.gui.models import WizardState
from dsm2emp.gui.workers import ScanWorker
from dsm2emp.scanner.inventory import PackageInventory


class ScanPage(QWizardPage):
    """Step 2: Package Inventory Scan Page."""

    def __init__(self, state: WizardState, parent: QWizardPage | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._worker: ScanWorker | None = None

        self.setTitle("Schritt 2: DSM-Paket scannen")
        self.setSubTitle("Erfassung aller Skripte, Registry-Dateien und Quellmedien.")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate while scanning
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("Bereite Scan vor...")
        layout.addWidget(self.status_lbl)

        # Artifact Tree View
        self.tree = QTreeWidget()
        headers = ["Artefakt / Pfad", "Kategorie", "Encoding", "Groesse", "SHA-256"]
        self.tree.setHeaderLabels(headers)
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 90)
        self.tree.setColumnWidth(3, 90)
        layout.addWidget(self.tree)

        # Stats footer
        self.stats_layout = QHBoxLayout()
        self.count_lbl = QLabel("Dateien: 0")
        self.hash_lbl = QLabel("Tree-Hash: -")
        self.stats_layout.addWidget(self.count_lbl)
        self.stats_layout.addStretch()
        self.stats_layout.addWidget(self.hash_lbl)
        layout.addLayout(self.stats_layout)

    def initializePage(self) -> None:
        """Trigger background scan when entering page."""
        self.tree.clear()
        if not self.state.source_dir:
            return

        if self.state.inventory is not None:
            self._on_scanned(self.state.inventory)
            return

        self.progress_bar.setVisible(True)
        self.status_lbl.setText("Scanne Quellordner...")

        self._worker = ScanWorker(self.state.source_dir)
        self._worker.scanned.connect(self._on_scanned)
        self._worker.failed.connect(self._on_scan_failed)
        self._worker.start()

    def _on_scanned(self, inventory: PackageInventory) -> None:
        """Populate tree view when inventory is ready."""
        self.state.inventory = inventory
        self.progress_bar.setVisible(False)
        self.status_lbl.setText(
            f"Scan erfolgreich abgeschlossen ({len(inventory.artifacts)} Dateien)."
        )

        self.count_lbl.setText(f"Dateien erfasst: {len(inventory.artifacts)}")
        short_hash = inventory.tree_hash[:16] + "..." if inventory.tree_hash else "-"
        self.hash_lbl.setText(f"Tree-Hash: {short_hash}")

        # Group by category/kind with expressive symbols
        groups: dict[str, QTreeWidgetItem] = {
            "script": QTreeWidgetItem(["📜 Skripte (eScript, INC)", "", "", "", ""]),
            "registry": QTreeWidgetItem(["⚙️ Registry (REG, NIR)", "", "", "", ""]),
            "source_media": QTreeWidgetItem(["📦 Quellmedien / Binaries", "", "", "", ""]),
            "unknown": QTreeWidgetItem(["📄 Sonstige / Metadaten", "", "", "", ""]),
        }

        for root_item in groups.values():
            self.tree.addTopLevelItem(root_item)

        from PySide6.QtGui import QColor

        for art in inventory.artifacts:
            kind_group = groups.get(art.kind, groups["unknown"])
            if art.size_bytes >= 1024:
                size_kb = f"{round(art.size_bytes / 1024, 1)} KB"
            else:
                size_kb = f"{art.size_bytes} B"
            enc = art.encoding or ("Binaer" if art.is_binary else "-")
            h = art.sha256[:12] + "..." if art.sha256 else "-"

            item = QTreeWidgetItem(
                [
                    str(art.rel_path),
                    art.kind,
                    enc,
                    size_kb,
                    h,
                ]
            )

            # Color-code encoding
            enc_lower = enc.lower()
            if "utf-8" in enc_lower:
                item.setForeground(2, QColor("#22c55e"))
            elif "cp1252" in enc_lower or "1252" in enc_lower or "ansi" in enc_lower:
                item.setForeground(2, QColor("#38bdf8"))
            elif "binaer" in enc_lower:
                item.setForeground(2, QColor("#94a3b8"))

            kind_group.addChild(item)

        self.tree.expandAll()
        self.completeChanged.emit()

    def _on_scan_failed(self, error: str) -> None:
        self.progress_bar.setVisible(False)
        self.status_lbl.setText(f"Fehler beim Scannen: {error}")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self.state.inventory is not None
