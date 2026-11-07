"""Unit and integration tests for package manual generation.

Verifies folder 'Manual' and '<PackageName>.pdf'.
"""

from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from dsm2emp.builder.builder import BuilderOptions, PackageBuilder
from dsm2emp.fixtures.make_packages import (
    create_p01_pure_msi,
    create_p02_exe_params,
    create_p04_registry,
)
from dsm2emp.manual.extractor import extract_manual_info, sanitize_filename
from dsm2emp.manual.generator import generate_manual_pdf
from dsm2emp.manual.model import PackageManualInfo
from dsm2emp.orchestrator import MigrationOptions, migrate_single
from dsm2emp.scanner.scanner import scan


def test_sanitize_filename() -> None:
    """Filename sanitizer must remove or replace invalid Windows characters."""
    assert sanitize_filename("NormalPackage") == "NormalPackage"
    bad_name = 'Bad:Name*With"Chars/And\\Pipes|And?Dots.'
    assert sanitize_filename(bad_name) == "Bad_Name_With_Chars_And_Pipes_And_Dots"
    assert sanitize_filename("   Spaces Around   ") == "Spaces Around"
    assert sanitize_filename("...dots...") == "dots"
    assert sanitize_filename("???") == "Softwarepaket"


def test_extract_manual_info_msi(tmp_path: Path) -> None:
    """Extractor identifies MSI package, silent parameter /qn, and metadata."""
    src = create_p01_pure_msi(tmp_path / "src")
    inventory = scan(src)

    inf_content = (
        "[Product]\n"
        "--Set:Product, DONTDELETE\n\n"
        "[Set:Product]\n"
        'Call MsiExec /I "%Src%\\app.msi" TRANSFORMS="%Src%\\setup.mst" /qn\n'
    )

    info = extract_manual_info(inventory=inventory, inf_content=inf_content)

    assert info.package_name == "PureMSIApp"
    assert info.product_name == "PureMSIApp"
    assert info.manufacturer == "TestCorp"
    assert info.version == "1.0"
    assert ".msi" in info.package_type
    assert "/qn" in info.silent_parameters
    assert "TRANSFORMS=" in info.silent_parameters
    assert "PureMSIApp" in info.description
    assert "TestCorp" in info.description

    # Basic parameters
    assert "Produktname" in info.basic_parameters
    assert "Hersteller" in info.basic_parameters
    assert "Paketversion" in info.basic_parameters
    assert "Paket-Typ" in info.basic_parameters
    assert "Silent-Installationsparameter" in info.basic_parameters
    assert "Installations-Kontext" in info.basic_parameters
    assert "Installations-Zielpfad" in info.basic_parameters
    assert "Neustart-Verhalten" in info.basic_parameters
    assert "Unterstützte Plattform" in info.basic_parameters
    assert "Setup.inf Skriptpfad" in info.basic_parameters
    assert "Payload-Verzeichnis" in info.basic_parameters

    assert len(info.payload_files) == 2
    filenames = [f[0] for f in info.payload_files]
    assert "app.msi" in filenames
    assert "setup.mst" in filenames


def test_extract_manual_info_exe_params(tmp_path: Path) -> None:
    """Extractor identifies Inno Setup / unattended EXE and /VERYSILENT."""
    src = create_p02_exe_params(tmp_path / "src")
    inventory = scan(src)

    inf_content = (
        "[Product]\n"
        "--Set:Product, DONTDELETE\n\n"
        "[Set:Product]\n"
        'Call "%Src%\\setup.exe" /DIR="%ProgramFiles%\\Vendor Suite\\App" /VERYSILENT\n'
    )

    info = extract_manual_info(inventory=inventory, inf_content=inf_content)

    assert "unattend" in info.package_type
    assert "/VERYSILENT" in info.silent_parameters
    assert "%ProgramFiles%\\Vendor Suite\\App" in info.basic_parameters["Installations-Zielpfad"]


def test_extract_manual_info_registry_package(tmp_path: Path) -> None:
    """Extractor classifies registry package when no media executables are present."""
    src = create_p04_registry(tmp_path / "src")
    inventory = scan(src)

    info = extract_manual_info(inventory=inventory, inf_content="; Registry Setup.inf")
    assert "Registry" in info.package_type or "Konfiguration" in info.package_type


def test_generate_manual_pdf_content(tmp_path: Path) -> None:
    """Generated PDF must contain all requested fields and valid structure."""
    pdf_path = tmp_path / "Manual" / "PureMSIApp.pdf"

    info = PackageManualInfo(
        package_name="PureMSIApp",
        product_name="PureMSIApp",
        manufacturer="TestCorp",
        version="2.5",
        conversion_timestamp=datetime(2026, 10, 3, 23, 15, 0),
        package_type=".msi (Windows Installer Paket)",
        silent_parameters='/qn TRANSFORMS="setup.mst"',
        description=(
            "Kurzbeschreibung des Pakets: Automatisierte Installation der Unternehmensanwendung."
        ),
        basic_parameters={
            "Produktname": "PureMSIApp",
            "Hersteller": "TestCorp",
            "Paketversion": "2.5",
            "Paket-Typ": ".msi (Windows Installer Paket)",
            "Silent-Installationsparameter": '/qn TRANSFORMS="setup.mst"',
            "Installations-Kontext": "Maschine (Computer)",
            "Installations-Zielpfad": "%ProgramFiles%\\PureMSIApp",
            "Neustart-Verhalten": "Kein Neustart erforderlich (Reboot=0)",
            "Unterstützte Plattform": "x64 (64-Bit)",
            "Setup.inf Skriptpfad": "Install\\Setup.inf",
            "Payload-Verzeichnis": "Files\\",
            "Zeichensatz (Setup.inf)": "Windows-1252 (CP1252 / ANSI)",
        },
        payload_files=[
            ("app.msi", 8192, "abcdef123456..."),
            ("setup.mst", 2048, "fedcba654321..."),
        ],
        command_lines=['Call MsiExec /I "%Src%\\app.msi" TRANSFORMS="%Src%\\setup.mst" /qn'],
    )

    result_path = generate_manual_pdf(info, pdf_path)
    assert result_path == pdf_path
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000

    # Verify content using pypdf
    reader = PdfReader(str(pdf_path))
    assert len(reader.pages) >= 1
    extracted_text = "\n".join(page.extract_text() for page in reader.pages)

    # Verify required elements per prompt
    assert "TestCorp" in extracted_text  # Herstellername
    assert "PureMSIApp" in extracted_text  # Produktname
    assert "03.10.2026" in extracted_text  # Datum
    assert "23:15:00" in extracted_text  # Uhrzeit
    assert ".msi" in extracted_text  # Art des Pakets
    assert "/qn" in extracted_text  # Silent Parameter
    assert "Kurzbeschreibung des Pakets" in extracted_text  # Kurzbeschreibung des Pakets
    assert "Basisparameter des Softwarepakets" in extracted_text  # Basisparameter
    assert "Installations-Zielpfad" in extracted_text
    assert "Neustart-Verhalten" in extracted_text
    assert "Unterstützte Plattform" in extracted_text
    assert "Enthaltene Payload-Dateien" in extracted_text
    assert "app.msi" in extracted_text
    assert "setup.mst" in extracted_text
    assert "Seite 1 von" in extracted_text


def test_package_builder_creates_manual_folder_and_pdf(tmp_path: Path) -> None:
    """PackageBuilder must create 'Manual' folder and '<PackageName>.pdf' in target."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    inventory = scan(src)

    builder = PackageBuilder()
    res = builder.build_package(tgt, "; Test Inf Content", inventory)

    manual_dir = tgt / "Manual"
    assert manual_dir.exists()
    assert manual_dir.is_dir()

    pdf_file = manual_dir / "PureMSIApp.pdf"
    assert pdf_file.exists()
    assert pdf_file.stat().st_size > 1000
    assert res.manual_dir == manual_dir
    assert res.manual_pdf_path == pdf_file


def test_package_builder_can_disable_manual(tmp_path: Path) -> None:
    """PackageBuilder respects generate_manual=False option."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    inventory = scan(src)

    builder = PackageBuilder(BuilderOptions(generate_manual=False))
    res = builder.build_package(tgt, "; Test Inf Content", inventory)

    assert not (tgt / "Manual").exists()
    assert res.manual_dir is None
    assert res.manual_pdf_path is None


def test_migrate_single_e2e_generates_manual_pdf(tmp_path: Path) -> None:
    """Full migration creates 'Manual/<PackageName>.pdf' with all metadata populated."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"

    opts = MigrationOptions(
        developer_name="TestVendorInc",
        product_name="CustomPureMSI",
        version="3.0",
    )
    result = migrate_single(src, tgt, options=opts)

    assert result.success is True
    assert result.build_result is not None

    manual_pdf = tgt / "Manual" / "CustomPureMSI.pdf"
    assert manual_pdf.exists()
    assert manual_pdf == result.build_result.manual_pdf_path

    # Verify extracted text from PDF
    reader = PdfReader(str(manual_pdf))
    full_text = "\n".join(page.extract_text() for page in reader.pages)
    assert "CustomPureMSI" in full_text
    assert "TestVendorInc" in full_text
    assert "3.0" in full_text
    assert ".msi" in full_text
    assert "/qn" in full_text


def test_manual_charset_label_matches_builder_charset(tmp_path: Path) -> None:
    """Regression: the manual must document the charset actually used by the
    builder (default: UTF-8 with BOM), not a hardcoded ANSI label."""
    from dsm2emp.fixtures.make_packages import create_p01_pure_msi
    from dsm2emp.scanner.scanner import scan

    src = create_p01_pure_msi(tmp_path / "src")
    inventory = scan(src)

    default_info = extract_manual_info(inventory=inventory, inf_content="")
    assert default_info.basic_parameters["Zeichensatz (Setup.inf)"] == "UTF-8 (mit BOM)"

    ansi_info = extract_manual_info(inventory=inventory, inf_content="", inf_charset="cp1252")
    assert ansi_info.basic_parameters["Zeichensatz (Setup.inf)"] == "Windows-1252 (CP1252 / ANSI)"
