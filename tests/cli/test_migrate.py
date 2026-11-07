"""Tests for CLI migration and scan commands (Task T-040)."""

from pathlib import Path

from typer.testing import CliRunner

from dsm2emp.cli import app
from tests.fixtures.make_packages import (
    create_p01_pure_msi,
    create_p02_exe_params,
    create_p04_registry,
)

runner = CliRunner()


def test_cli_scan(tmp_path: Path) -> None:
    """Test 'dsm2emp scan' outputs artifacts and table for a DSM package."""
    pkg_dir = create_p01_pure_msi(tmp_path / "dsm_pkg")
    result = runner.invoke(app, ["scan", str(pkg_dir)])

    assert result.exit_code == 0
    assert "Package Inventory:" in result.output
    assert "Media: 2" in result.output
    assert "app.msi" in result.output


def test_cli_migrate_p01(tmp_path: Path) -> None:
    """Test 'dsm2emp migrate' on P-01 package."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"

    result = runner.invoke(app, ["migrate", str(src), str(tgt)])
    # Succeeded (exit code 0 or 1 for warnings/TODOs)
    assert result.exit_code in (0, 1)
    assert (tgt / "Install" / "Setup.inf").exists()
    assert (tgt / "Files" / "app.msi").exists()
    assert (tgt / "Files" / "setup.mst").exists()


def test_cli_migrate_p02(tmp_path: Path) -> None:
    """Test 'dsm2emp migrate' on P-02 package."""
    src = create_p02_exe_params(tmp_path / "src")
    tgt = tmp_path / "tgt"

    result = runner.invoke(app, ["migrate", str(src), str(tgt)])
    assert result.exit_code in (0, 1)
    inf_file = tgt / "Install" / "Setup.inf"
    assert inf_file.exists()
    assert (tgt / "Files" / "setup.exe").exists()


def test_cli_migrate_p04(tmp_path: Path) -> None:
    """Test 'dsm2emp migrate' on P-04 registry package."""
    src = create_p04_registry(tmp_path / "src")
    tgt = tmp_path / "tgt"

    result = runner.invoke(app, ["migrate", str(src), str(tgt)])
    assert result.exit_code in (0, 1)
    inf_file = tgt / "Install" / "Setup.inf"
    assert inf_file.exists()
    content = inf_file.read_text(encoding="cp1252")
    assert "[Reg:Product]" in content


def test_cli_migrate_collision_target_inside_source(tmp_path: Path) -> None:
    """Target directory inside source directory must fail with exit code 3."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = src / "nested_target"

    result = runner.invoke(app, ["migrate", str(src), str(tgt)])
    assert result.exit_code == 3
    assert "E9001" in result.output
    clean_out = " ".join(result.output.split())
    assert "cannot be inside source directory" in clean_out


def test_cli_migrate_collision_source_inside_target(tmp_path: Path) -> None:
    """Source directory inside target directory must fail with exit code 3."""
    src = tmp_path / "parent" / "nested_source"
    create_p01_pure_msi(src)
    tgt = tmp_path / "parent"

    result = runner.invoke(app, ["migrate", str(src), str(tgt)])
    assert result.exit_code == 3
    assert "E9001" in result.output
    clean_out = " ".join(result.output.split())
    assert "cannot be inside target directory" in clean_out


def test_cli_migrate_target_not_empty_without_force(tmp_path: Path) -> None:
    """Target directory not empty without --force must fail with exit code 3."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    tgt.mkdir(parents=True, exist_ok=True)
    (tgt / "existing.txt").write_text("already here")

    result = runner.invoke(app, ["migrate", str(src), str(tgt)])
    assert result.exit_code == 3
    clean_out = " ".join(result.output.split())
    assert "is not empty. Use --force to allow overwriting" in clean_out


def test_cli_migrate_target_not_empty_with_force(tmp_path: Path) -> None:
    """Target directory not empty with --force must succeed."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    tgt.mkdir(parents=True, exist_ok=True)
    (tgt / "existing.txt").write_text("already here")

    result = runner.invoke(app, ["migrate", str(src), str(tgt), "--force"])
    assert result.exit_code in (0, 1)
    assert (tgt / "Install" / "Setup.inf").exists()


def test_cli_selftest() -> None:
    """dsm2emp selftest must exit with code 0."""
    result = runner.invoke(app, ["selftest"])
    assert result.exit_code == 0
    assert "DSM2Empirum self-test: OK" in result.output
