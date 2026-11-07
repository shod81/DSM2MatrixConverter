"""Capture high-resolution screenshots of all DSM2Empirum GUI screens and wizard steps."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidgetItem

from dsm2emp.gui.app import create_app
from dsm2emp.gui.batch_window import BatchWindow
from dsm2emp.gui.models import WizardState
from dsm2emp.gui.start_window import StartWindow
from dsm2emp.gui.wizard.wizard import MigrationWizard
from dsm2emp.orchestrator import MigrationOptions, migrate_single
from dsm2emp.scanner.scanner import scan

REPO_ROOT = Path(__file__).resolve().parents[1]


def create_rich_enterprise_package(root: Path) -> Path:
    """Create a rich package with scripts, binaries, registry, and conditions."""
    pkg_dir = root / "EnterpriseApp_2026_x64"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # Binaries
    (pkg_dir / "setup.exe").write_bytes(b"MZ" + b"\x00" * 4096)
    (pkg_dir / "setup.msi").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 8192)
    (pkg_dir / "config.xml").write_text(
        "<config><license>Enterprise</license></config>", encoding="utf-8"
    )
    reg_content = (
        "Windows Registry Editor Version 5.00\r\n\r\n"
        "[HKEY_LOCAL_MACHINE\\SOFTWARE\\EnterpriseApp]\r\n"
        '"Enabled"=dword:00000001\r\n'
    )
    (pkg_dir / "settings.reg").write_text(reg_content, encoding="utf-8")

    script_content = (
        "; DSM eScript EnterpriseApp Setup\r\n"
        "Set(TargetDir, '%ProgramFiles%\\EnterpriseApp')\r\n"
        "Set(SilentArgs, '/qn ALLUSERS=1 REBOOT=ReallySuppress')\r\n"
        "If %IsRunningOnX64% = '1'\r\n"
        "  ExecuteEx('msiexec.exe /i \"%Src%\\setup.msi\" %SilentArgs%', 'ErrorLevel', '0')\r\n"
        "  If %ErrorLevel% != '0'\r\n"
        "    ExitProcEx(Failed, 'Installation failed')\r\n"
        "  EndIf\r\n"
        "  RegModify('HKLM', 'Software\\EnterpriseApp', 'Installed', 'REG_DWORD', '1')\r\n"
        "  Copy('%Src%\\config.xml', '%TargetDir%\\config.xml')\r\n"
        "Else\r\n"
        "  ExitProcEx(Undetermined, 'x86 architecture not supported')\r\n"
        "EndIf\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))
    (pkg_dir / "Package.ini").write_text(
        "[Package]\r\nName=EnterpriseApp\r\nVersion=2026.1\r\nManufacturer=Contoso Global\r\n",
        encoding="utf-8",
    )
    return pkg_dir


def main() -> None:
    app = create_app()

    repo_out = REPO_ROOT / "docs" / "screenshots"
    repo_out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create realistic sample package
        src_pkg = create_rich_enterprise_package(tmp_path / "src")
        tgt_pkg = tmp_path / "tgt"
        res = migrate_single(src_pkg, tgt_pkg, MigrationOptions(force=True))
        inventory = scan(src_pkg)

        # 1. Start Window
        print("Capturing 01_start_window.png...")
        start_win = StartWindow()
        start_win.show()
        app.processEvents()
        pix_start = start_win.grab()
        pix_start.save(str(repo_out / "01_start_window.png"))
        start_win.close()

        # 2. Wizard Pages
        state = WizardState(
            source_dir=src_pkg,
            target_dir=tgt_pkg,
            inventory=inventory,
            migration_result=res,
        )
        wizard = MigrationWizard(state)
        wizard.show()
        app.processEvents()

        # Step 1: Select
        print("Capturing 02_wizard_step1_select.png...")
        wizard.page_select.src_edit.setText(str(src_pkg))
        wizard.page_select.tgt_edit.setText(r"C:\Empirum_Depot\EnterpriseApp_2026_x64_Empirum")
        wizard.page_select._on_src_changed(str(src_pkg))
        # Show a neutral path instead of the temporary build directory.
        wizard.page_select.src_edit.blockSignals(True)
        wizard.page_select.src_edit.setText(r"C:\DSM_Export\EnterpriseApp_2026_x64")
        wizard.page_select.src_edit.blockSignals(False)
        app.processEvents()
        wizard.grab().save(str(repo_out / "02_wizard_step1_select.png"))

        # Step 2: Scan
        print("Capturing 03_wizard_step2_scan.png...")
        wizard.next()  # Move to Step 2
        wizard.page_scan.initializePage()
        wizard.page_scan.tree.expandAll()
        app.processEvents()
        wizard.grab().save(str(repo_out / "03_wizard_step2_scan.png"))

        # Step 3: Mapping
        print("Capturing 04_wizard_step3_mapping.png...")
        wizard.next()  # Move to Step 3
        wizard.page_mapping.initializePage()
        wizard.page_mapping.progress_bar.setVisible(False)
        wizard.page_mapping.status_lbl.setText(
            "Transformation erfolgreich abgeschlossen (10 Befehle analysiert)."
        )
        wizard.page_mapping.summary_badge.setText("Konfidenz Ø: 89% (Ampel: GRÜN) · 2 TODOs")
        wizard.page_mapping.summary_badge.setStyleSheet(
            "color: #22c55e; font-weight: bold; font-size: 13px;"
        )
        if wizard.page_mapping.table.rowCount() > 2:
            it = wizard.page_mapping.table.item(2, 0)
            if it:
                wizard.page_mapping.table.setCurrentItem(it)
                wizard.page_mapping._on_item_clicked(it)
        app.processEvents()
        wizard.grab().save(str(repo_out / "04_wizard_step3_mapping.png"))

        # Step 4: Diff & Issues
        print("Capturing 05_wizard_step4_diff.png...")
        wizard.next()  # Move to Step 4
        wizard.page_diff.initializePage()
        # Add sample info issue
        wizard.page_diff.issues_table.setRowCount(2)
        sev1 = QTableWidgetItem("INFO")
        sev1.setForeground(QColor("#38bdf8"))
        wizard.page_diff.issues_table.setItem(0, 0, sev1)
        wizard.page_diff.issues_table.setItem(0, 1, QTableWidgetItem("INF-010"))
        wizard.page_diff.issues_table.setItem(
            0, 2, QTableWidgetItem("Header [SetupInfo] und [Application] vollstaendig generiert")
        )
        wizard.page_diff.issues_table.setItem(0, 3, QTableWidgetItem("Application"))

        sev2 = QTableWidgetItem("WARNING")
        sev2.setForeground(QColor("#eab308"))
        wizard.page_diff.issues_table.setItem(1, 0, sev2)
        wizard.page_diff.issues_table.setItem(1, 1, QTableWidgetItem("SEC-004"))
        wizard.page_diff.issues_table.setItem(
            1, 2, QTableWidgetItem("RegModify-Befehl erfordert manuelle Pruefung im Zielsystem")
        )
        wizard.page_diff.issues_table.setItem(1, 3, QTableWidgetItem("Reg:Product"))

        app.processEvents()
        wizard.grab().save(str(repo_out / "05_wizard_step4_diff.png"))

        # Step 5: Export
        print("Capturing 06_wizard_step5_export.png...")
        wizard.next()  # Move to Step 5
        wizard.page_export.initializePage()
        wizard.page_export.tgt_edit.setText(r"C:\Empirum_Depot\EnterpriseApp_2026_x64_Empirum")
        wizard.page_export.open_explorer_btn.setEnabled(True)
        wizard.page_export.open_html_btn.setEnabled(True)
        wizard.page_export.open_md_btn.setEnabled(True)
        wizard.page_export.summary_lbl.setText(
            "Paket erfolgreich erstellt!\n"
            "- Zielordner: C:\\Empirum_Depot\\EnterpriseApp_2026_x64_Empirum\n"
            "- Dateien kopiert: 4 (setup.exe, setup.msi, config.xml, settings.reg)\n"
            "- Setup.inf: C:\\Empirum_Depot\\EnterpriseApp_2026_x64_Empirum\\Install\\Setup.inf\n"
            "- SHA-256 Integritaetspruefung: 100% verifiziert"
        )
        app.processEvents()
        wizard.grab().save(str(repo_out / "06_wizard_step5_export.png"))
        wizard.close()

        # 3. Batch Window (Initial)
        print("Capturing 07_batch_window_initial.png...")
        batch_win = BatchWindow()
        batch_win.show()
        app.processEvents()
        batch_win.grab().save(str(repo_out / "07_batch_window_initial.png"))

        # 4. Batch Window (Completed with rich data)
        print("Capturing 08_batch_window_completed.png...")
        batch_win.src_lbl.setText(r"C:\DSM_Repository\Production_Packages")
        batch_win.tgt_lbl.setText(r"C:\Empirum_Depot\Migrated_Packages")

        sample_packages = [
            ("7-Zip_24.08_x64", "OK", "#22c55e", "96%", "0", "1.2s"),
            ("Adobe_Acrobat_DC_2024", "OK", "#22c55e", "91%", "2", "3.8s"),
            ("Google_Chrome_129_Enterprise", "OK", "#22c55e", "94%", "1", "2.1s"),
            ("Cisco_AnyConnect_4.10", "WARNINGS", "#eab308", "78%", "5", "4.5s"),
            ("Legacy_ERP_Client_v3", "WARNINGS", "#eab308", "65%", "9", "6.2s"),
            ("Custom_Internal_Agent_x86", "OK", "#22c55e", "88%", "3", "1.9s"),
        ]

        batch_win.table.setRowCount(len(sample_packages))
        for row, (name, status, color_hex, conf, todos, dur) in enumerate(sample_packages):
            batch_win.table.setItem(row, 0, QTableWidgetItem(name))
            s_item = QTableWidgetItem(status)
            s_item.setForeground(QColor(color_hex))
            batch_win.table.setItem(row, 1, s_item)
            c_item = QTableWidgetItem(conf)
            batch_win.table.setItem(row, 2, c_item)
            t_item = QTableWidgetItem(todos)
            batch_win.table.setItem(row, 3, t_item)
            d_item = QTableWidgetItem(dur)
            batch_win.table.setItem(row, 4, d_item)

        batch_win.progress_bar.setRange(0, len(sample_packages))
        batch_win.progress_bar.setValue(len(sample_packages))
        batch_win.status_footer.setText(
            f"Batch abgeschlossen: {len(sample_packages)} Pakete "
            f"(4 erfolgreich, 2 mit Warnungen, 0 Fehler) · Gesamtdauer 19.7s"
        )
        batch_win.open_summary_btn.setEnabled(True)
        app.processEvents()
        batch_win.grab().save(str(repo_out / "08_batch_window_completed.png"))
        batch_win.close()

    print(f"Successfully generated 8 screenshots in {repo_out}")


if __name__ == "__main__":
    main()
