"""Pytest execution of golden file test suites (Task T-041)."""

from pathlib import Path

import pytest

from tests.golden.__main__ import GOLDEN_ROOT, run_scenario

scenarios = [d for d in sorted(GOLDEN_ROOT.iterdir()) if d.is_dir() and (d / "input").exists()]


@pytest.mark.parametrize(
    "scenario_dir",
    scenarios,
    ids=[s.name for s in scenarios],
)
def test_golden_scenario(scenario_dir: Path) -> None:
    """Run golden test scenario and verify exact byte-for-byte output match."""
    ok, msg = run_scenario(scenario_dir, bless=False)
    assert ok, msg
