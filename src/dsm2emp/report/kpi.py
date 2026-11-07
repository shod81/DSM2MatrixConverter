"""Key Performance Indicator (KPI) calculations for DSM2Empirum migrations (Task T-044).

Implements deterministic confidence averaging (Chapter 5.4) and quality metrics.
The counting and weighting logic lives in rules.model (single source of truth);
this module adapts it to MigrationResult and re-exports the shared helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dsm2emp.io.encoding import read_text
from dsm2emp.orchestrator import MigrationResult
from dsm2emp.rules.model import (  # noqa: F401  (re-exported for compatibility)
    COLOR_GREEN_THRESHOLD,
    COLOR_YELLOW_THRESHOLD,
    CONFIDENCE_WEIGHTS,
    confidence_color,
    count_constructs,
    weighted_average_confidence,
)


def todo_quote_pct(total_constructs: int, todo_count: int) -> float:
    """TODO share of all constructs in percent, rounded to one decimal."""
    if total_constructs <= 0:
        return 0.0
    return round(todo_count / total_constructs * 100, 1)


@dataclass(frozen=True)
class MigrationKpi:
    """KPI metrics for a single package migration."""

    package_name: str
    lines_dsm: int
    lines_setup_inf: int
    total_constructs: int
    constructs_high: int
    constructs_medium: int
    constructs_low: int
    constructs_todo: int
    average_confidence: float
    confidence_color: Literal["green", "yellow", "red"]
    todo_count: int
    todo_quote_pct: float
    error_count: int
    warning_count: int
    is_valid: bool


def calculate_kpis(
    result: MigrationResult,
    setup_inf_content: str | None = None,
) -> MigrationKpi:
    """Calculate deterministic KPIs from a MigrationResult."""
    # Count DSM lines from main script (BOM-aware encoding detection)
    lines_dsm = 0
    if result.inventory.main_script and result.inventory.main_script.absolute_path.exists():
        try:
            script_text, _ = read_text(result.inventory.main_script.absolute_path)
            lines_dsm += len(script_text.splitlines())
        except OSError:
            pass

    # Count Setup.inf lines (BOM-aware read; the builder writes UTF-8 with BOM)
    lines_setup_inf = 0
    if setup_inf_content is not None:
        lines_setup_inf = len(setup_inf_content.splitlines())
    elif result.target_root:
        inf_file = result.target_root / "Install" / "Setup.inf"
        if inf_file.exists():
            try:
                inf_text, _ = read_text(inf_file)
                lines_setup_inf = len(inf_text.splitlines())
            except OSError:
                pass

    traces = result.transform_result.traces if result.transform_result else []
    todos = result.transform_result.todos if result.transform_result else []

    # Single source of truth for counting (avoids double-counting TODOs that
    # also appear as todo-confidence traces)
    counts = count_constructs(traces, todos)

    todo_count = counts["todo_items"]
    total_constructs = counts["total_constructs"]

    # Confidence calculation per Chapter 5.4 (single source of truth in rules.model)
    avg_conf = weighted_average_confidence(
        counts["high"], counts["medium"], counts["low"], counts["todo"]
    )
    conf_color = confidence_color(avg_conf)
    todo_quote = todo_quote_pct(total_constructs, counts["todo"])

    errors = sum(1 for i in result.issues if i.severity == "error")
    warnings = sum(1 for i in result.issues if i.severity == "warning")

    return MigrationKpi(
        package_name=result.source_root.name,
        lines_dsm=lines_dsm,
        lines_setup_inf=lines_setup_inf,
        total_constructs=total_constructs,
        constructs_high=counts["high"],
        constructs_medium=counts["medium"],
        constructs_low=counts["low"],
        constructs_todo=counts["todo"],
        average_confidence=avg_conf,
        confidence_color=conf_color,
        todo_count=todo_count,
        todo_quote_pct=todo_quote,
        error_count=errors,
        warning_count=warnings,
        is_valid=errors == 0,
    )
