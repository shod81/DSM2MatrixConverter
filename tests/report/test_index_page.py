"""Unit tests for the Paketindex.html generator (src/dsm2emp/report/index_page.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dsm2emp.cli import app
from dsm2emp.report.index_page import (
    generate_package_index,
    render_index_html,
    scan_output_directory,
)


@pytest.fixture
def sample_output_dir(tmp_path: Path) -> Path:
    """Create a simulated Empirum_Output directory with various packages."""
    out = tmp_path / "Empirum_Output"
    out.mkdir()

    # Package 1: GUID-named folder with Install/Setup.inf
    pkg1 = out / "{5A1F2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}"
    install1 = pkg1 / "Install"
    install1.mkdir(parents=True)
    (install1 / "Setup.inf").write_text(
        """[SetupInfo]
Dskptn=Setup.inf

[Application]
ProductName=SAP GUI 8.00
Version=8.00
DeveloperName=SAP SE
SetupInfDir=Install
""",
        encoding="cp1252",
    )

    # Package 2: Human-named folder with Umlauts in Setup.inf
    pkg2 = out / "B_EDIUS_Schnittsoftware"
    install2 = pkg2 / "Install"
    install2.mkdir(parents=True)
    (install2 / "Setup.inf").write_text(
        """[SetupInfo]
Dskptn=Setup.inf

[Application]
ProductName="Grass Valley EDIUS Pro"
Version=11.00
DeveloperName="Grass Valley & Co."
""",
        encoding="utf-8",
    )

    # Package 3: Folder without Setup.inf (incomplete / failed migration)
    pkg3 = out / "Incomplete_App"
    pkg3.mkdir()
    (pkg3 / "readme.txt").write_text("Not ready", encoding="utf-8")

    return out


def test_scan_output_directory(sample_output_dir: Path) -> None:
    """Verify that packages, metadata, and fallback folders are properly discovered."""
    entries = scan_output_directory(sample_output_dir)

    assert len(entries) == 3

    # Sorted alphabetically by ProductName
    # 1. Grass Valley EDIUS Pro
    # 2. Incomplete_App
    # 3. SAP GUI 8.00
    names = [e.product_name for e in entries]
    assert names == ["Grass Valley EDIUS Pro", "Incomplete_App", "SAP GUI 8.00"]

    # Check SAP GUI details
    sap = next(e for e in entries if e.product_name == "SAP GUI 8.00")
    assert sap.folder_name == "{5A1F2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}"
    assert sap.version == "8.00"
    assert sap.developer_name == "SAP SE"
    assert sap.has_setup_inf is True
    assert sap.setup_inf_rel_path == "{5A1F2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}/Install/Setup.inf"
    assert sap.status == "Bereit"

    # Check Grass Valley details
    edius = next(e for e in entries if e.product_name == "Grass Valley EDIUS Pro")
    assert edius.folder_name == "B_EDIUS_Schnittsoftware"
    assert edius.version == "11.00"
    assert edius.developer_name == "Grass Valley & Co."
    assert edius.has_setup_inf is True

    # Check Incomplete App details
    inc = next(e for e in entries if e.product_name == "Incomplete_App")
    assert inc.folder_name == "Incomplete_App"
    assert inc.version == "-"
    assert inc.has_setup_inf is False
    assert inc.status == "Ohne Setup.inf"


def test_render_index_html_escaping_and_content(sample_output_dir: Path) -> None:
    """Verify HTML rendering, XSS safety, and action buttons."""
    entries = scan_output_directory(sample_output_dir)
    html_text = render_index_html(entries, sample_output_dir)

    assert "<!DOCTYPE html>" in html_text
    assert "DSM2Empirum Paket-Index" in html_text
    assert "SAP GUI 8.00" in html_text
    assert "{5A1F2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D}" in html_text
    assert "Grass Valley &amp; Co." in html_text  # Escaped &
    assert "copyPath(" in html_text
    assert "searchInput" in html_text


def test_generate_package_index_file(sample_output_dir: Path) -> None:
    """Verify that generate_package_index writes Paketindex.html directly into output dir."""
    index_path = generate_package_index(sample_output_dir)

    assert index_path.exists()
    assert index_path.name == "Paketindex.html"
    content = index_path.read_text(encoding="utf-8")
    assert "Paketindex – Empirum Output" in content
    assert "SAP GUI 8.00" in content


def test_cli_index_command(sample_output_dir: Path) -> None:
    """Test CLI command `dsm2emp index <output_dir>`."""
    runner = CliRunner()
    result = runner.invoke(app, ["index", str(sample_output_dir)])

    assert result.exit_code == 0
    assert "Paketindex erfolgreich erstellt" in result.output
    assert (sample_output_dir / "Paketindex.html").exists()


def test_index_meta_reads_own_utf8_bom_output(tmp_path: Path) -> None:
    """Regression: the builder writes Setup.inf as UTF-8 with BOM; the index
    must decode it as UTF-8 (not cp1252) so umlauts render correctly."""
    pkg = tmp_path / "Pkg"
    (pkg / "Install").mkdir(parents=True)
    content = (
        "[Application]\r\n"
        "ProductName=Systemüberwachung\r\n"
        "DeveloperName=Müller AG\r\n"
        "Version=1.0\r\n"
    )
    (pkg / "Install" / "Setup.inf").write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

    entries = scan_output_directory(tmp_path)
    assert len(entries) == 1
    assert entries[0].product_name == "Systemüberwachung"
    assert entries[0].developer_name == "Müller AG"
