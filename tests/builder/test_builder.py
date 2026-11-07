"""Unit and integration tests for PackageBuilder (Task T-042)."""

from pathlib import Path

import pytest

from dsm2emp.builder.builder import BuilderOptions, PackageBuilder, check_path_collision
from dsm2emp.fixtures.make_packages import create_p01_pure_msi
from dsm2emp.scanner.scanner import scan


def test_builder_default_layout(tmp_path: Path) -> None:
    """Builder creates Install/Setup.inf and copies payload to Files/."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    inventory = scan(src)

    builder = PackageBuilder()
    res = builder.build_package(tgt, "; Test Inf Content", inventory)

    assert res.target_root == tgt.resolve()
    assert res.setup_inf_path == tgt.resolve() / "Install" / "Setup.inf"
    assert res.payload_dir == tgt.resolve() / "Files"
    assert res.setup_inf_path.exists()
    assert (tgt / "Files" / "app.msi").exists()
    assert (tgt / "Files" / "setup.mst").exists()
    assert res.hashes_verified is True
    assert res.total_bytes_copied > 0
    assert len(res.copied_files) == 2


def test_builder_custom_layout(tmp_path: Path) -> None:
    """Builder respects custom setup_inf_dir and payload_dir."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    inventory = scan(src)

    builder = PackageBuilder(
        BuilderOptions(setup_inf_dir="CustomInstall", payload_dir="CustomPayload")
    )
    res = builder.build_package(tgt, "; Custom Inf", inventory)

    assert res.setup_inf_path == tgt.resolve() / "CustomInstall" / "Setup.inf"
    assert res.payload_dir == tgt.resolve() / "CustomPayload"
    assert res.setup_inf_path.exists()
    assert (tgt / "CustomPayload" / "app.msi").exists()


def test_builder_collision_target_in_source(tmp_path: Path) -> None:
    """Target directory inside source directory must raise ValueError with E9001."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = src / "nested_target"

    with pytest.raises(ValueError, match="E9001"):
        check_path_collision(src, tgt)


def test_builder_collision_source_in_target(tmp_path: Path) -> None:
    """Source directory inside target directory must raise ValueError with E9001."""
    src = tmp_path / "parent" / "nested_source"
    create_p01_pure_msi(src)
    tgt = tmp_path / "parent"

    with pytest.raises(ValueError, match="E9001"):
        check_path_collision(src, tgt)


def test_builder_collision_identical(tmp_path: Path) -> None:
    """Identical source and target paths must raise ValueError with E9001."""
    src = create_p01_pure_msi(tmp_path / "src")

    with pytest.raises(ValueError, match="E9001"):
        check_path_collision(src, src)


def test_builder_target_not_empty_without_force(tmp_path: Path) -> None:
    """Target directory not empty without force must raise FileExistsError."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    tgt.mkdir(parents=True, exist_ok=True)
    (tgt / "dummy.txt").write_text("existing content")
    inventory = scan(src)

    builder = PackageBuilder(BuilderOptions(force=False))
    with pytest.raises(FileExistsError, match="not empty"):
        builder.build_package(tgt, "; Content", inventory)


def test_builder_target_not_empty_with_force(tmp_path: Path) -> None:
    """Target directory not empty with force=True succeeds."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    tgt.mkdir(parents=True, exist_ok=True)
    (tgt / "dummy.txt").write_text("existing content")
    inventory = scan(src)

    builder = PackageBuilder(BuilderOptions(force=True))
    res = builder.build_package(tgt, "; Content", inventory)
    assert res.setup_inf_path.exists()


def test_builder_hash_tamper_detection(tmp_path: Path) -> None:
    """If payload hash differs, builder raises IOError during verification."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    inventory = scan(src)

    # Tamper with the inventory hash of app.msi
    tampered_artifacts = [
        art.model_copy(update={"sha256": "0" * 64}) if art.rel_path.name == "app.msi" else art
        for art in inventory.artifacts
    ]
    tampered_inv = inventory.model_copy(update={"artifacts": tampered_artifacts})

    builder = PackageBuilder(BuilderOptions(verify_hashes=True))
    with pytest.raises(IOError, match="Payload hash verification failed"):
        builder.build_package(tgt, "; Content", tampered_inv)


def test_builder_extern_subdirectories_preserved(tmp_path: Path) -> None:
    """Change 1: Files in extern$ preserve subfolder structure under Files/."""
    src = tmp_path / "src"
    (src / "Extern$" / "Msidata").mkdir(parents=True, exist_ok=True)
    (src / "Extern$" / "setup.msi").write_text("dummy msi")
    (src / "Extern$" / "Msidata" / "transform.mst").write_text("dummy mst")
    (src / "Extern$" / "config.ini").write_text("dummy ini")
    (src / "Script.inc").write_text("!Test")

    inventory = scan(src)
    tgt = tmp_path / "tgt"
    builder = PackageBuilder()
    res = builder.build_package(tgt, "; Test", inventory)

    assert (tgt / "Files" / "setup.msi").exists()
    assert (tgt / "Files" / "Msidata" / "transform.mst").exists()
    assert (tgt / "Files" / "config.ini").exists()
    assert len(res.copied_files) == 3


def test_builder_custom_subdirectories_preserved(tmp_path: Path) -> None:
    """Non-extern payload subfolders (e.g. FONT, Grass Valley) are preserved under Files/."""
    src = tmp_path / "src"
    (src / "FONT").mkdir(parents=True, exist_ok=True)
    (src / "FONT" / "testfont.otf").write_text("dummy font data")
    (src / "Grass Valley" / "EDIUS").mkdir(parents=True, exist_ok=True)
    (src / "Grass Valley" / "EDIUS" / "config.xml").write_text("<xml/>")
    (src / "Script.inc").write_text("!Test")

    inventory = scan(src)
    tgt = tmp_path / "tgt"
    builder = PackageBuilder()
    res = builder.build_package(tgt, "; Test", inventory)

    assert (tgt / "Files" / "FONT" / "testfont.otf").exists()
    assert (tgt / "Files" / "Grass Valley" / "EDIUS" / "config.xml").exists()
    assert len(res.copied_files) == 2


def test_builder_dollar_extern_preserved(tmp_path: Path) -> None:
    """$Extern folder works identically to Extern$, stripping $Extern prefix."""
    src = tmp_path / "src"
    (src / "$Extern" / "fonts").mkdir(parents=True, exist_ok=True)
    (src / "$Extern" / "fonts" / "barcode.ttf").write_text("dummy ttf")
    (src / "Script.inc").write_text("!Test")

    inventory = scan(src)
    tgt = tmp_path / "tgt"
    builder = PackageBuilder()
    res = builder.build_package(tgt, "; Test", inventory)

    assert (tgt / "Files" / "fonts" / "barcode.ttf").exists()
    assert len(res.copied_files) == 1


def test_builder_rollback_removes_partial_target_on_failure(tmp_path: Path) -> None:
    """Regression: a mid-build failure (hash mismatch) must not leave a
    half-written package behind; the builder rolls back its own artifacts."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    inventory = scan(src)

    tampered_artifacts = [
        art.model_copy(update={"sha256": "0" * 64}) if art.rel_path.name == "app.msi" else art
        for art in inventory.artifacts
    ]
    tampered_inv = inventory.model_copy(update={"artifacts": tampered_artifacts})

    builder = PackageBuilder(BuilderOptions(verify_hashes=True))
    with pytest.raises(IOError, match="Payload hash verification failed"):
        builder.build_package(tgt, "; Content", tampered_inv)

    assert not tgt.exists()


def test_builder_rollback_on_manual_failure_preserves_existing_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing manual PDF generation rolls back created files/dirs but must
    not touch pre-existing content in an existing target directory."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    tgt.mkdir(parents=True)
    (tgt / "keepme.txt").write_text("keep me")
    inventory = scan(src)

    def _fail(info: object, path: Path) -> Path:
        raise RuntimeError("pdf engine exploded")

    monkeypatch.setattr("dsm2emp.builder.builder.generate_manual_pdf", _fail)

    builder = PackageBuilder(BuilderOptions(force=True, generate_manual=True))
    with pytest.raises(RuntimeError, match="pdf engine exploded"):
        builder.build_package(tgt, "; Content", inventory)

    assert (tgt / "keepme.txt").exists()
    assert not (tgt / "Install").exists()
    assert not (tgt / "Files").exists()
    assert not (tgt / "Manual").exists()


def test_builder_writes_ansi_without_bom(tmp_path: Path) -> None:
    """Setup.inf must be Windows-1252 without BOM (VAL-030): Empirum Setup.exe and the
    Package Editor read ANSI and exit immediately on BOM-prefixed files."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    inventory = scan(src)

    builder = PackageBuilder()
    res = builder.build_package(
        tgt, "[SetupInfo]\r\nInstallationFor=Installation für:\r\n", inventory
    )

    raw = res.setup_inf_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert not raw.startswith(b"\xff\xfe")
    assert b"f\xfcr" in raw  # umlaut stored as a single CP1252 byte, not UTF-8 multi-byte
    assert "Installation für:" in raw.decode("cp1252")
