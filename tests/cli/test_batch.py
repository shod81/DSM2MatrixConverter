"""Tests for batch migration, worker pool, resume state, and 50-package AK-6 run (Task T-043)."""

import json
from pathlib import Path

from typer.testing import CliRunner

from dsm2emp.batch import BatchOptions, discover_packages, migrate_batch
from dsm2emp.cli import app
from dsm2emp.fixtures.make_packages import (
    _make_dummy_binary,
    create_p01_pure_msi,
    create_p02_exe_params,
)

runner = CliRunner()


def test_discover_packages_sorting(tmp_path: Path) -> None:
    """Discovered packages are sorted deterministically."""
    # Create packages with out-of-order names
    for name in ("pkg_c", "pkg_a", "pkg_b"):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "Script.inc").write_text("; Script\r\n", encoding="cp1252")

    discovered = discover_packages(tmp_path)
    names = [d.name for d in discovered]
    assert names == ["pkg_a", "pkg_b", "pkg_c"]


def test_batch_migration_sequential(tmp_path: Path) -> None:
    """Sequential batch migration creates target structures and state.ndjson."""
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    p1 = create_p01_pure_msi(src)
    p2 = create_p02_exe_params(src)

    res = migrate_batch(src, tgt, BatchOptions(jobs=1, force=True))
    assert res.total_packages == 2
    assert res.successful + res.warnings == 2
    assert res.failed == 0

    assert (tgt / p1.name / "Install" / "Setup.inf").exists()
    assert (tgt / p2.name / "Install" / "Setup.inf").exists()

    state_file = tgt / "state.ndjson"
    assert state_file.exists()
    records = [
        json.loads(line) for line in state_file.read_text(encoding="utf-8").splitlines() if line
    ]
    assert len(records) == 2


def test_batch_migration_parallel(tmp_path: Path) -> None:
    """Parallel batch migration with worker threads succeeds."""
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    create_p01_pure_msi(src / "pkg1")
    create_p01_pure_msi(src / "pkg2")
    create_p01_pure_msi(src / "pkg3")

    res = migrate_batch(src, tgt, BatchOptions(jobs=3, force=True))
    assert res.total_packages == 3
    assert res.failed == 0


def test_batch_resume(tmp_path: Path) -> None:
    """Running with resume=True skips already completed packages."""
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    create_p01_pure_msi(src / "pkg1")
    create_p01_pure_msi(src / "pkg2")

    # Run 1
    res1 = migrate_batch(src, tgt, BatchOptions(jobs=1, force=True))
    assert res1.total_packages == 2
    assert res1.skipped == 0

    # Run 2 with resume
    res2 = migrate_batch(src, tgt, BatchOptions(jobs=1, resume=True, force=True))
    assert res2.total_packages == 2
    assert res2.skipped == 2
    assert len(res2.results) == 0  # No new packages were run


def test_batch_cli_command(tmp_path: Path) -> None:
    """Typer CLI command 'dsm2emp batch' functions as expected."""
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    p1 = create_p01_pure_msi(src)

    result = runner.invoke(app, ["batch", str(src), str(tgt), "--jobs", "2", "--force"])
    assert result.exit_code in (0, 1)
    assert "Batch Summary:" in result.output
    assert "Total: 1" in result.output
    assert (tgt / p1.name / "Install" / "Setup.inf").exists()


def test_ak6_fifty_synthetic_packages_batch(tmp_path: Path) -> None:
    """AK-6: Batch over 50 synthetic packages: 0 crashes, correct aggregated report."""
    src = tmp_path / "src_50"
    tgt = tmp_path / "tgt_50"
    src.mkdir(parents=True, exist_ok=True)

    # Generate 50 unique packages
    for i in range(1, 51):
        pkg_dir = src / f"App_{i:02d}"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        _make_dummy_binary(pkg_dir / f"app_{i:02d}.msi", size_kb=4)
        script_code = (
            f"; DSM eScript Synthetic Package {i:02d}\r\n"
            f"ExecuteEx('msiexec.exe /i \"%Src%\\\\app_{i:02d}.msi\" /qn', 'rc', '0')\r\n"
            f"If %rc% != '0'\r\n"
            f"  ExitProcEx(Failed, 'Installation failed')\r\n"
            f"EndIf\r\n"
        )
        (pkg_dir / "Script.inc").write_bytes(script_code.encode("cp1252"))
        (pkg_dir / "Package.ini").write_text(
            f"[Package]\nName=App_{i:02d}\nVersion=1.{i}\nManufacturer=VendorCorp\n",
            encoding="utf-8",
        )

    discovered = discover_packages(src)
    assert len(discovered) == 50

    # Execute batch with 4 concurrent workers
    res = migrate_batch(src, tgt, BatchOptions(jobs=4, force=True))

    # AK-6 assertions: 0 crashes, 0 failed, 50 processed
    assert res.total_packages == 50
    assert res.failed == 0
    assert res.successful + res.warnings == 50
    assert len(res.results) == 50

    # Verify state.ndjson has exactly 50 records
    state_file = tgt / "state.ndjson"
    assert state_file.exists()
    records = [
        json.loads(line) for line in state_file.read_text(encoding="utf-8").splitlines() if line
    ]
    assert len(records) == 50

    # Verify Setup.inf created for every package
    for i in range(1, 51):
        inf_file = tgt / f"App_{i:02d}" / "Install" / "Setup.inf"
        assert inf_file.exists(), f"Setup.inf missing for App_{i:02d}"


def test_batch_options_default_charset_is_cp1252() -> None:
    """VAL-030 regression guard: BatchOptions (GUI batch window default path) must
    default to Windows-1252 - Empirum reads ANSI only and exits on anything else."""
    assert BatchOptions().charset == "cp1252"
