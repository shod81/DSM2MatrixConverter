"""Collect pilot KPI statistics from a batch migration output directory (Task T-110).

Reads ``state.ndjson`` from a batch run (``dsm2emp batch <src> <tgt>``) and re-runs the
deterministic read-only analysis pipeline (scan -> parse -> rule transform) on each
migrated package's SOURCE directory to compute exact per-package KPIs:

* TODO-Quote (share of TODO constructs, Chapter 5.4)
* Konfidenzverteilung (high/medium/low/todo counts, weighted average, Ampel color)

Output: two CSV files (UTF-8 with BOM, Excel-friendly) for the pilot review:

* ``<prefix>_packages.csv``  - one row per package
* ``<prefix>_summary.csv``   - aggregate metrics (distribution across the batch)

The source packages are only ever read (FR-001); nothing is written outside the
CSV prefix location. AI assistance is not applied (offline default, NFR-001).

Usage:
    python tools/collect_stats.py <batch_output_dir> [--out-prefix PREFIX] [--rules-file FILE]
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from dsm2emp.io.encoding import read_text
from dsm2emp.parser.escript.parser import parse_script
from dsm2emp.parser.ir import IrPackage
from dsm2emp.parser.nir import parse_nir
from dsm2emp.report.kpi import todo_quote_pct
from dsm2emp.rules.engine import RuleEngine
from dsm2emp.rules.loader import load_rules
from dsm2emp.rules.model import confidence_color, count_constructs, weighted_average_confidence
from dsm2emp.scanner.scanner import scan

console = Console()

CSV_COLUMNS = [
    "package_name",
    "status",
    "exit_code",
    "setup_inf_present",
    "total_constructs",
    "high",
    "medium",
    "low",
    "todo",
    "todo_quote_pct",
    "average_confidence",
    "confidence_color",
    "note",
]


def load_state_records(batch_dir: Path) -> list[dict[str, Any]]:
    """Load state.ndjson, keeping the LAST record per package (resume appends)."""
    state_file = batch_dir / "state.ndjson"
    if not state_file.exists():
        raise FileNotFoundError(
            f"state.ndjson not found in '{batch_dir}'. "
            "Run 'dsm2emp batch <source> <target>' first - this tool runs on batch output."
        )
    latest: dict[str, dict[str, Any]] = {}
    with open(state_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = str(record.get("package_name", ""))
            if name:
                latest[name] = record
    return list(latest.values())


def analyze_source_readonly(source: Path, rules_path: Path | None) -> dict[str, Any]:
    """Run the read-only analysis pipeline and return KPI counts (no writes)."""
    inventory = scan(source)

    main_ir = None
    if inventory.main_script:
        script_text, _ = read_text(inventory.main_script.absolute_path)
        main_ir = parse_script(script_text, inventory.main_script.absolute_path)

    parsed_nirs: list[Any] = []
    for reg_art in inventory.nirs + inventory.regs:
        reg_text, _ = read_text(reg_art.absolute_path)
        parsed_nirs.extend(parse_nir(reg_text, reg_art.absolute_path))

    pkg_ir = IrPackage(
        name=inventory.root_path.name,
        version="1.0",
        manufacturer="Matrix42",
        main_script=main_ir,
        todos=[],
    )
    ruleset = load_rules(rules_path)
    transform = RuleEngine(ruleset).transform_package(
        pkg_ir,
        parsed_nirs=parsed_nirs,
        developer_name="Matrix42",
        product_name=pkg_ir.name,
        version=pkg_ir.version,
    )

    traces = transform.traces
    todos = transform.todos
    counts: dict[str, Any] = dict(count_constructs(traces, todos))
    # keep the pilot CSV schema stable: todo_items is an internal KPI detail
    counts.pop("todo_items", None)
    counts["average_confidence"] = weighted_average_confidence(
        counts["high"], counts["medium"], counts["low"], counts["todo"]
    )
    counts["confidence_color"] = confidence_color(counts["average_confidence"])
    counts["todo_quote_pct"] = todo_quote_pct(counts["total_constructs"], counts["todo"])
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export pilot KPIs (TODO-Quote, Konfidenzverteilung) as CSV "
        "from a batch migration output directory."
    )
    parser.add_argument("batch_dir", type=Path, help="Batch output directory (with state.ndjson)")
    parser.add_argument(
        "--out-prefix",
        type=Path,
        default=None,
        help="CSV output prefix (default: <batch_dir>/pilot_stats)",
    )
    parser.add_argument("--rules-file", type=Path, default=None, help="Custom rules YAML")
    args = parser.parse_args(argv)

    batch_dir = args.batch_dir.resolve()
    records = load_state_records(batch_dir)
    if not records:
        console.print("[bold red]state.ndjson contains no package records.[/bold red]")
        return 2

    prefix = (args.out_prefix or batch_dir / "pilot_stats").resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for rec in sorted(records, key=lambda r: str(r.get("package_name", ""))):
        name = str(rec.get("package_name", "?"))
        row: dict[str, Any] = {col: "" for col in CSV_COLUMNS}
        row["package_name"] = name
        row["status"] = str(rec.get("status", ""))
        row["exit_code"] = str(rec.get("exit_code", ""))

        target = rec.get("target_path")
        if target:
            row["setup_inf_present"] = str((Path(str(target)) / "Install" / "Setup.inf").is_file())

        source = rec.get("source_path")
        if not source or not Path(str(source)).is_dir():
            row["note"] = "source directory missing - KPIs skipped"
            rows.append(row)
            continue
        try:
            row.update(analyze_source_readonly(Path(str(source)), args.rules_file))
        except Exception as err:  # one broken package must not kill the export
            row["note"] = f"analysis failed: {err}"
        rows.append(row)

    packages_csv = prefix.with_name(prefix.name + "_packages.csv")
    with open(packages_csv, "w", encoding="utf-8-sig", newline="") as f:
        packages_writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        packages_writer.writeheader()
        packages_writer.writerows(rows)

    # Aggregate distribution across the batch
    analyzed = [r for r in rows if r["total_constructs"] != ""]
    totals = {
        key: sum(int(r[key]) for r in analyzed)
        for key in ("total_constructs", "high", "medium", "low", "todo")
    }
    avg_batch = weighted_average_confidence(
        totals["high"], totals["medium"], totals["low"], totals["todo"]
    )
    status_counts = {
        s: sum(1 for r in rows if r["status"] == s) for s in ("success", "warning", "failed")
    }
    color_counts = {
        c: sum(1 for r in analyzed if r["confidence_color"] == c)
        for c in ("green", "yellow", "red")
    }
    summary_rows = [
        ("generated_at", datetime.datetime.now(datetime.UTC).isoformat()),
        ("batch_dir", str(batch_dir)),
        ("packages_total", len(rows)),
        ("packages_analyzed", len(analyzed)),
        ("packages_status_success", status_counts["success"]),
        ("packages_status_warning", status_counts["warning"]),
        ("packages_status_failed", status_counts["failed"]),
        ("packages_setup_inf_present", sum(1 for r in rows if r["setup_inf_present"] == "True")),
        ("total_constructs", totals["total_constructs"]),
        ("traces_high", totals["high"]),
        ("traces_medium", totals["medium"]),
        ("traces_low", totals["low"]),
        ("todos", totals["todo"]),
        (
            "todo_quote_pct_overall",
            todo_quote_pct(totals["total_constructs"], totals["todo"]),
        ),
        ("average_confidence_overall", avg_batch),
        ("packages_color_green", color_counts["green"]),
        ("packages_color_yellow", color_counts["yellow"]),
        ("packages_color_red", color_counts["red"]),
    ]
    summary_csv = prefix.with_name(prefix.name + "_summary.csv")
    with open(summary_csv, "w", encoding="utf-8-sig", newline="") as f:
        summary_writer = csv.writer(f)
        summary_writer.writerow(["metric", "value"])
        summary_writer.writerows(summary_rows)

    table = Table(title="Pilot-KPIs (Gesamtverteilung)")
    table.add_column("Metrik", style="cyan")
    table.add_column("Wert", justify="right")
    for metric, value in summary_rows:
        if metric in ("batch_dir", "generated_at"):
            continue
        table.add_row(metric, str(value))
    console.print(table)
    console.print(f"Pakete-CSV:      [bold]{packages_csv}[/bold]")
    console.print(f"Zusammenfassung: [bold]{summary_csv}[/bold]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
