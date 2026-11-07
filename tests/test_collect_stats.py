"""End-to-end test for the pilot KPI export (T-110): batch output -> CSV."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from dsm2emp.batch import BatchOptions, migrate_batch
from dsm2emp.fixtures.make_packages import create_p01_pure_msi
from tools.collect_stats import main as collect_stats_main


def test_collect_stats_runs_on_batch_output(tmp_path: Path) -> None:
    source = create_p01_pure_msi(tmp_path / "src" / "P-01")
    target = tmp_path / "tgt"
    result = migrate_batch(source.parent, target, BatchOptions())
    # P-01 migrates cleanly without warnings (exit 0)
    assert result.successful == 1
    assert result.warnings == 0
    assert result.failed == 0

    state_file = target / "state.ndjson"
    assert state_file.is_file()

    exit_code = collect_stats_main([str(target)])
    assert exit_code == 0

    packages_csv = target / "pilot_stats_packages.csv"
    summary_csv = target / "pilot_stats_summary.csv"
    assert packages_csv.is_file()
    assert summary_csv.is_file()

    with open(packages_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    row = rows[0]
    assert row["package_name"].startswith("P-01")
    assert row["setup_inf_present"] == "True"
    assert int(row["total_constructs"]) >= 1
    assert row["confidence_color"] in ("green", "yellow", "red")
    assert float(row["average_confidence"]) >= 0.1

    with open(summary_csv, encoding="utf-8-sig", newline="") as f:
        summary = dict(csv.reader(f))
    assert summary["packages_total"] == "1"
    assert summary["packages_status_success"] == "1"
    assert summary["packages_status_warning"] == "0"


def test_collect_stats_fails_cleanly_without_state(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="state.ndjson"):
        collect_stats_main([str(tmp_path)])
