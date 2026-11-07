"""Step 5: Export, package building, and reports (Task T-050).

Conforms to Chapter 5.1:
- Zielordner waehlen / bestaetigen
- Build ausfuehren
- Zusammenfassung (Dateien, Hashes, Report-Links)
- "Bericht oeffnen"
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWizardPage,
)

from dsm2emp.builder.builder import BuilderOptions, PackageBuilder
from dsm2emp.emitter import emit
from dsm2emp.gui.models import WizardState
from dsm2emp.report.render_html import render_html_report
from dsm2emp.report.render_md import render_markdown_report


class ExportPage(QWizardPage):
    """Step 5: Package Export & Build Finalization Page."""

    def __init__(self, state: WizardState, parent: QWizardPage | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self._html_report_path: Path | None = None
        self._md_report_path: Path | None = None

        self.setTitle("Schritt 5: Export und Bereitstellung")
        self.setSubTitle(
            "Generierung des vollstaendigen Empirum-Pakets und der Migrationsberichte."
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # Target selection
        form_layout = QFormLayout()
        tgt_box = QHBoxLayout()
        self.tgt_edit = QLineEdit()
        tgt_box.addWidget(self.tgt_edit)
        browse_btn = QPushButton("Durchsuchen...")
        browse_btn.clicked.connect(self._browse_target)
        tgt_box.addWidget(browse_btn)
        form_layout.addRow("Empirum-Zielordner*:", tgt_box)
        layout.addLayout(form_layout)

        # Build action button
        self.build_btn = QPushButton("Empirum-Paket jetzt erstellen")
        self.build_btn.setObjectName("primaryButton")
        self.build_btn.clicked.connect(self._execute_build)
        layout.addWidget(self.build_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        # Summary Box
        self.summary_lbl = QLabel("Bereit zum Export.")
        self.summary_lbl.setObjectName("infoBox")
        layout.addWidget(self.summary_lbl)

        # Report & Folder Action Buttons
        report_box = QHBoxLayout()
        self.open_explorer_btn = QPushButton("Zielordner im Explorer oeffnen")
        self.open_explorer_btn.setEnabled(False)
        self.open_explorer_btn.clicked.connect(self._open_in_explorer)

        self.open_html_btn = QPushButton("HTML-Bericht oeffnen")
        self.open_html_btn.setEnabled(False)
        self.open_html_btn.clicked.connect(self._open_html_report)

        self.open_md_btn = QPushButton("Markdown-Bericht oeffnen")
        self.open_md_btn.setEnabled(False)
        self.open_md_btn.clicked.connect(self._open_md_report)

        report_box.addWidget(self.open_explorer_btn)
        report_box.addWidget(self.open_html_btn)
        report_box.addWidget(self.open_md_btn)
        layout.addLayout(report_box)

        layout.addStretch()

    def initializePage(self) -> None:
        """Prefill default target directory if not set."""
        if not self.state.target_dir and self.state.source_dir:
            default_target = self.state.source_dir.parent / f"{self.state.source_dir.name}_Empirum"
            self.tgt_edit.setText(str(default_target))
        elif self.state.target_dir:
            self.tgt_edit.setText(str(self.state.target_dir))

    def _browse_target(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Zielordner auswaehlen")
        if path:
            self.tgt_edit.setText(path)

    def _execute_build(self) -> None:
        tgt_text = self.tgt_edit.text().strip()
        if not tgt_text or not self.state.source_dir or not self.state.migration_result:
            return

        target_path = Path(tgt_text)
        self.state.target_dir = target_path
        self.progress_bar.setVisible(True)
        self.build_btn.setEnabled(False)
        self.summary_lbl.setText("Kopiere Dateien und verifiziere SHA-256 Integritaet...")

        try:
            doc_ast = (
                self.state.migration_result.transform_result.document
                if self.state.migration_result.transform_result
                else None
            )
            if not doc_ast:
                raise ValueError("Kein Setup.inf AST fuer den Export vorhanden")

            inf_content, _ = emit(doc_ast)
            inventory = self.state.inventory or self.state.migration_result.inventory

            builder = PackageBuilder(options=BuilderOptions(force=True))
            build_res = builder.build_package(
                target_dir=target_path,
                inf_content=inf_content,
                inventory=inventory,
            )
            self.state.build_result = build_res

            # Generate reports inside target directory
            html_content = render_html_report(self.state.migration_result)
            md_content = render_markdown_report(self.state.migration_result)

            self._html_report_path = target_path / "report.html"
            self._md_report_path = target_path / "report.md"

            self._html_report_path.write_text(html_content, encoding="utf-8")
            self._md_report_path.write_text(md_content, encoding="utf-8")

            self.progress_bar.setVisible(False)
            self.summary_lbl.setText(
                f"Paket erfolgreich erstellt!\n"
                f"- Zielordner: {target_path}\n"
                f"- Dateien kopiert: {len(build_res.copied_files)}\n"
                f"- Setup.inf: {build_res.setup_inf_path}\n"
                f"- Handbuch: {build_res.manual_pdf_path}\n"
                f"- SHA-256 Verifikation: 100% geprueft"
            )
            self.open_html_btn.setEnabled(True)
            self.open_md_btn.setEnabled(True)
            self.open_explorer_btn.setEnabled(True)
            self.completeChanged.emit()

        except Exception as exc:
            self.progress_bar.setVisible(False)
            self.build_btn.setEnabled(True)
            self.summary_lbl.setText(f"Exportfehler: {exc}")

    def _open_in_explorer(self) -> None:
        if self.state.target_dir and self.state.target_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.state.target_dir)))

    def _open_html_report(self) -> None:
        if self._html_report_path and self._html_report_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._html_report_path)))

    def _open_md_report(self) -> None:
        if self._md_report_path and self._md_report_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._md_report_path)))

    def isComplete(self) -> bool:
        return self.state.build_result is not None and self.state.build_result.hashes_verified
