"""Data models for transformation rules, rule catalog, and transformation traces."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dsm2emp.ast.nodes import InfDocument
from dsm2emp.parser.ir import IrTodo

Confidence = Literal["high", "medium", "low", "todo"]

# Chapter 5.4 confidence weights - SINGLE SOURCE OF TRUTH.
# Used by the rule engine (TransformResult.average_confidence), report/kpi.py and
# tools/collect_stats.py; do not duplicate these numbers elsewhere.
CONFIDENCE_WEIGHTS: dict[Confidence, float] = {
    "high": 1.0,
    "medium": 0.7,
    "low": 0.4,
    "todo": 0.1,
}

# Chapter 5.4 Ampel thresholds
COLOR_GREEN_THRESHOLD = 0.85
COLOR_YELLOW_THRESHOLD = 0.60


def weighted_average_confidence(high: int, medium: int, low: int, todo: int) -> float:
    """Deterministic confidence average (Chapter 5.4): hoch=1.0 mittel=0.7 niedrig=0.4 TODO=0.1."""
    total = high + medium + low + todo
    if total == 0:
        return 1.0
    weighted_sum = (
        high * CONFIDENCE_WEIGHTS["high"]
        + medium * CONFIDENCE_WEIGHTS["medium"]
        + low * CONFIDENCE_WEIGHTS["low"]
        + todo * CONFIDENCE_WEIGHTS["todo"]
    )
    return round(weighted_sum / total, 2)


def confidence_color(average_confidence: float) -> Literal["green", "yellow", "red"]:
    """Map an average confidence to the traffic-light color (Chapter 5.4)."""
    if average_confidence >= COLOR_GREEN_THRESHOLD:
        return "green"
    if average_confidence >= COLOR_YELLOW_THRESHOLD:
        return "yellow"
    return "red"


def unrepresented_todos(traces: Sequence[RuleTrace], todos: Sequence[IrTodo]) -> list[IrTodo]:
    """Return todos that have no matching trace and must be counted as extra constructs.

    Every TODO emitted by the rule engine also produces a RuleTrace for the same
    construct (identical source line and raw text). Only todos without such a
    trace (e.g. parse-level todos) represent constructs not contained in traces.
    """
    trace_keys = {(t.source_line, t.source_raw) for t in traces}
    return [td for td in todos if (td.src.line, td.raw) not in trace_keys]


def count_constructs(traces: Sequence[RuleTrace], todos: Sequence[IrTodo]) -> dict[str, int]:
    """Single source of truth for construct/KPI counting (Chapter 5.4).

    One DSM construct corresponds to exactly one RuleTrace. "todo" in the result
    is the number of todo-confidence constructs (todo traces + todos without any
    trace); "todo_items" is the number of open review items (len(todos)) and may
    differ from "todo" only for hybrid cases (e.g. RunAsEx emits a medium trace
    plus a review todo for the same construct).
    """
    extra_todos = unrepresented_todos(traces, todos)
    counts: dict[str, int] = {
        "total_constructs": len(traces) + len(extra_todos),
        "high": sum(1 for t in traces if t.confidence == "high"),
        "medium": sum(1 for t in traces if t.confidence == "medium"),
        "low": sum(1 for t in traces if t.confidence == "low"),
        "todo": sum(1 for t in traces if t.confidence == "todo") + len(extra_todos),
        "todo_items": len(todos),
    }
    return counts


class RuleDefinition(BaseModel):
    """Definition of a single mapping rule from DSM to Empirum."""

    model_config = ConfigDict(frozen=True)

    id: str  # e.g. M-01, V-01, C-01, S-01
    category: Literal["command", "variable", "condition", "structure"]
    kind: str  # Name of construct e.g. ExecuteEx, windir, CheckPlatform, etc.
    description: str
    doc_ref: str
    confidence: Confidence
    match: dict[str, Any] = Field(default_factory=dict)
    translate: dict[str, Any] = Field(default_factory=dict)


class RuleSet(BaseModel):
    """Collection of mapping rules loaded from YAML."""

    model_config = ConfigDict(frozen=True)

    version: int = 1
    doc_basis: str = ""
    rules: list[RuleDefinition] = Field(default_factory=list)

    def get_rule(self, rule_id: str) -> RuleDefinition | None:
        """Find rule by ID (e.g. 'M-01')."""
        for r in self.rules:
            if r.id.upper() == rule_id.upper():
                return r
        return None

    def get_command_rule(self, cmd_name: str) -> RuleDefinition | None:
        """Find rule matching command name."""
        cmd_lower = cmd_name.lower()
        for r in self.rules:
            if r.category == "command" and r.kind.lower() == cmd_lower:
                return r
        if cmd_lower in ("regmodify", "regmodifydword", "regmodifyqword", "regmodifymultisz"):
            return self.get_rule("M-10")
        return None

    def get_variable_rule(self, var_name: str) -> RuleDefinition | None:
        """Find rule matching variable name."""
        for r in self.rules:
            if r.category == "variable" and r.kind.lower() == var_name.lower():
                return r
        return None

    def get_condition_rule(self, cond_name: str) -> RuleDefinition | None:
        """Find rule matching condition construct."""
        for r in self.rules:
            if r.category == "condition" and r.kind.lower() == cond_name.lower():
                return r
        return None


class RuleTrace(BaseModel):
    """Audit trace record for a transformed construct."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    source_line: int
    source_raw: str
    confidence: Confidence
    target_summary: str
    doc_ref: str
    notes: list[str] = Field(default_factory=list)


class TransformResult(BaseModel):
    """Complete result of transforming a DSM IR package into an Empirum Setup.inf AST."""

    model_config = ConfigDict(frozen=True)

    document: InfDocument
    traces: list[RuleTrace] = Field(default_factory=list)
    todos: list[IrTodo] = Field(default_factory=list)
    average_confidence: float = 1.0

    @property
    def high_confidence_count(self) -> int:
        return sum(1 for t in self.traces if t.confidence == "high")

    @property
    def medium_confidence_count(self) -> int:
        return sum(1 for t in self.traces if t.confidence == "medium")

    @property
    def low_confidence_count(self) -> int:
        return sum(1 for t in self.traces if t.confidence == "low")

    @property
    def todo_count(self) -> int:
        """Number of open TODO review items (one per unhandled construct)."""
        return len(self.todos)
