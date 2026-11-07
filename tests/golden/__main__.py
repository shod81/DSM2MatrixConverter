"""CLI runner to run or bless golden file tests.

Usage:
    python -m tests.golden              # Run all golden tests and report diffs
    python -m tests.golden --bless      # Bless (update) all expected files
    python -m tests.golden --bless <id> # Bless a single scenario
"""

from __future__ import annotations

import argparse
import difflib
import sys
import tempfile
from pathlib import Path

import yaml

from dsm2emp.io.encoding import read_text, write_text
from dsm2emp.orchestrator import MigrationOptions, migrate_single

GOLDEN_ROOT = Path(__file__).resolve().parent


def load_scenario_meta(scenario_dir: Path) -> dict[str, str]:
    """Load optional meta.yaml for a scenario."""
    meta_path = scenario_dir / "meta.yaml"
    if meta_path.exists():
        data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    return {}


def run_scenario(scenario_dir: Path, bless: bool = False) -> tuple[bool, str]:
    """Run migration for a single scenario and compare/update expected files."""
    input_dir = scenario_dir / "input"
    expected_dir = scenario_dir / "expected"
    expected_inf = expected_dir / "Install" / "Setup.inf"

    if not input_dir.exists():
        return False, f"Missing input directory: {input_dir}"

    meta = load_scenario_meta(scenario_dir)
    dev_name = str(meta.get("developer_name") or "Matrix42")
    prod_name = meta.get("product_name")
    ver = meta.get("version")

    opts = MigrationOptions(
        developer_name=dev_name,
        product_name=prod_name,
        version=ver,
        force=True,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_tgt = Path(tmp_dir) / "output"
        res = migrate_single(input_dir, tmp_tgt, opts)
        if not res.success or res.exit_code not in (0, 1):
            return False, f"Migration failed with exit code {res.exit_code}: {res.error_message}"

        gen_inf_path = tmp_tgt / "Install" / "Setup.inf"
        if not gen_inf_path.exists():
            return False, "Migration did not generate Install/Setup.inf"

        # Byte-level gate: Empirum reads Setup.inf as ANSI/CP1252; a BOM or
        # non-ANSI bytes make the interpreter exit before anything runs.
        bom_err = f"BOM/encoding problem in generated Setup.inf of {scenario_dir.name}"
        raw = gen_inf_path.read_bytes()
        if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            return False, f"{bom_err}: file starts with a BOM (VAL-030)"
        try:
            raw.decode("cp1252")
        except UnicodeDecodeError as ex:
            return False, f"{bom_err}: not valid Windows-1252 ({ex}) (VAL-031)"

        gen_content, _ = read_text(gen_inf_path)

        if bless:
            expected_inf.parent.mkdir(parents=True, exist_ok=True)
            write_text(expected_inf, gen_content, charset="cp1252", crlf=True)
            return True, f"Blessed: {scenario_dir.name}"

        if not expected_inf.exists():
            return False, (
                f"Expected file does not exist: {expected_inf}. Run with --bless to create it."
            )

        exp_raw = expected_inf.read_bytes()
        if exp_raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            return False, f"Expected Setup.inf of {scenario_dir.name} has a BOM (VAL-030)"
        try:
            exp_raw.decode("cp1252")
        except UnicodeDecodeError as ex:
            return False, f"Expected Setup.inf of {scenario_dir.name} is not Windows-1252 ({ex})"

        exp_content, _ = read_text(expected_inf)
        if gen_content != exp_content:
            diff = "".join(
                difflib.unified_diff(
                    exp_content.splitlines(keepends=True),
                    gen_content.splitlines(keepends=True),
                    fromfile=f"expected/{scenario_dir.name}/Install/Setup.inf",
                    tofile=f"actual/{scenario_dir.name}/Install/Setup.inf",
                )
            )
            return False, f"Diff found in {scenario_dir.name}:\n{diff}"

        return True, f"OK: {scenario_dir.name}"


def main() -> int:
    """Entry point for golden tests runner and blesser."""
    parser = argparse.ArgumentParser(description="Golden file runner and blesser")
    parser.add_argument("--bless", nargs="?", const="all", help="Bless scenario(s)")
    args = parser.parse_args()

    scenarios = [d for d in sorted(GOLDEN_ROOT.iterdir()) if d.is_dir() and (d / "input").exists()]

    if not scenarios:
        print("No golden scenarios found in tests/golden/")
        return 0

    bless_target = args.bless
    target_scenarios = scenarios
    if bless_target and bless_target != "all":
        target_scenarios = [s for s in scenarios if s.name == bless_target]
        if not target_scenarios:
            print(f"Scenario not found: {bless_target}")
            return 1

    failures = 0
    for scen in target_scenarios:
        ok, msg = run_scenario(scen, bless=bool(bless_target))
        print(msg)
        if not ok:
            failures += 1

    return 1 if failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
