from pathlib import Path

import pytest

from dsm2emp.scanner.scanner import calculate_tree_hash, scan
from tests.fixtures.make_packages import (
    create_all_test_packages,
    create_p01_pure_msi,
    create_p04_registry,
    create_p09_encodings,
    create_p12_container_and_unknown,
)


def test_scanner_p01_pure_msi(tmp_path: Path) -> None:
    """Test scanner on P-01 (Pure MSI package)."""
    pkg_dir = create_p01_pure_msi(tmp_path)
    inv = scan(pkg_dir)

    assert inv.root_path == pkg_dir.resolve()
    assert len(inv.artifacts) == 4

    assert inv.main_script is not None
    assert inv.main_script.rel_path == Path("Script.inc")
    assert inv.main_script.kind == "script"
    assert inv.main_script.is_binary is False

    media_paths = {a.rel_path.name for a in inv.media}
    assert "app.msi" in media_paths
    assert "setup.mst" in media_paths

    metadata_paths = {a.rel_path.name for a in inv.metadata_files}
    assert "Package.ini" in metadata_paths


def test_scanner_p04_registry(tmp_path: Path) -> None:
    """Test scanner on P-04 (Registry with NIR file)."""
    pkg_dir = create_p04_registry(tmp_path)
    inv = scan(pkg_dir)

    nir_files = inv.nirs
    assert len(nir_files) == 1
    assert nir_files[0].rel_path == Path("setup.nir")
    assert nir_files[0].kind == "nir"
    assert nir_files[0].is_binary is False


def test_scanner_p09_encodings(tmp_path: Path) -> None:
    """Test scanner on P-09 (Various encodings)."""
    pkg_dir = create_p09_encodings(tmp_path)
    inv = scan(pkg_dir)

    art_ansi = inv.get_artifact("Script_ansi.inc")
    assert art_ansi is not None
    assert art_ansi.encoding == "cp1252"
    assert art_ansi.has_bom is False

    art_utf8bom = inv.get_artifact("Script_utf8bom.inc")
    assert art_utf8bom is not None
    assert art_utf8bom.encoding == "utf-8-sig"
    assert art_utf8bom.has_bom is True

    art_utf16le = inv.get_artifact("Script_utf16le.inc")
    assert art_utf16le is not None
    assert art_utf16le.encoding == "utf-16-le"
    assert art_utf16le.has_bom is True


def test_scanner_p12_container_and_unknowns(tmp_path: Path) -> None:
    """Test scanner on P-12 (NCP Container and Unknown files)."""
    pkg_dir = create_p12_container_and_unknown(tmp_path)
    inv = scan(pkg_dir)

    assert len(inv.containers) == 1
    container = inv.containers[0]
    assert container.rel_path == Path("package.ncp")
    assert "Export" in (container.reason or "")

    unknown_names = {a.rel_path.name for a in inv.unknowns}
    assert "mystery.xyz" in unknown_names
    assert "mystery.raw" in unknown_names
    for unk in inv.unknowns:
        assert unk.reason is not None and len(unk.reason) > 0


def test_scanner_read_only_tree_hash_immutability(tmp_path: Path) -> None:
    """FR-001 / T-101 Quellschutz-Selbsttest: Source package remains byte-identical."""
    pkg_dir = create_p01_pure_msi(tmp_path)

    hash_before = calculate_tree_hash(pkg_dir)
    assert len(hash_before) == 64

    # Perform scan
    inv = scan(pkg_dir)
    assert inv.tree_hash == hash_before

    hash_after = calculate_tree_hash(pkg_dir)
    assert hash_after == hash_before, "Source package was altered during scan!"


def test_scanner_all_test_packages(tmp_path: Path) -> None:
    """Test scanning across all P-01 through P-12 packages."""
    packages = create_all_test_packages(tmp_path)
    for pkg_id, pkg_dir in packages.items():
        inv = scan(pkg_dir)
        assert len(inv.artifacts) > 0, f"Package {pkg_id} should have artifacts"
        assert len(inv.tree_hash) == 64


def test_scanner_invalid_paths(tmp_path: Path) -> None:
    """Test error handling for non-existent path or file instead of directory."""
    with pytest.raises(FileNotFoundError):
        scan(tmp_path / "does_not_exist")

    dummy_file = tmp_path / "file.txt"
    dummy_file.write_text("hello", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        scan(dummy_file)


def test_scanner_empty_dir(tmp_path: Path) -> None:
    """Test scanning an empty directory."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    inv = scan(empty_dir)
    assert len(inv.artifacts) == 0
    assert len(inv.tree_hash) == 64


def test_scanner_ni5_zip_exclusion(tmp_path: Path) -> None:
    """Verify _NI5.zip cache files are classified as internal and excluded from media."""
    pkg_dir = tmp_path / "pkg_with_ni5"
    pkg_dir.mkdir()
    (pkg_dir / "Script.inc").write_text("; Script\n", encoding="cp1252")
    (pkg_dir / "setup.exe").write_bytes(b"\x00" * 100)
    (pkg_dir / "Package_NI5.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 50)
    (pkg_dir / "cache_ni5.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 50)

    inv = scan(pkg_dir)
    media_names = {m.rel_path.name for m in inv.media}
    internal_names = {i.rel_path.name for i in inv.internal_files}

    assert "setup.exe" in media_names
    assert "Package_NI5.zip" not in media_names
    assert "cache_ni5.zip" not in media_names

    assert "Package_NI5.zip" in internal_names
    assert "cache_ni5.zip" in internal_names
