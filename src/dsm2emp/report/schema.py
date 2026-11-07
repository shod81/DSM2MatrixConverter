"""JSON Schema and serializable report models for MigrationResult (Task T-044)."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, Field

from dsm2emp.orchestrator import MigrationResult
from dsm2emp.report.kpi import calculate_kpis


class ArtifactReport(BaseModel):
    """Artifact metadata report model."""

    rel_path: str
    category: str
    size_bytes: int
    sha256: str | None = None


class TraceReport(BaseModel):
    """Transformation rule trace model."""

    rule_id: str
    confidence: str
    target_summary: str
    doc_ref: str
    source_line: int | None = None
    source_raw: str = ""


class TodoReport(BaseModel):
    """TODO item model."""

    raw: str
    message: str
    confidence: float = 0.0
    line: int | None = None


class IssueReport(BaseModel):
    """Validation issue report model."""

    severity: str
    code: str
    message: str
    field: str | None = None


class MigrationResultReport(BaseModel):
    """Schema-validated complete report model for a package migration."""

    package_name: str
    exit_code: int
    success: bool
    source_root: str
    target_root: str | None = None
    tree_hash: str
    timestamp: str
    lines_dsm: int
    lines_setup_inf: int
    total_constructs: int
    average_confidence: float
    confidence_color: str
    todo_count: int
    todo_quote_pct: float
    error_count: int
    warning_count: int
    artifacts: list[ArtifactReport] = Field(default_factory=list)
    traces: list[TraceReport] = Field(default_factory=list)
    todos: list[TodoReport] = Field(default_factory=list)
    issues: list[IssueReport] = Field(default_factory=list)


def build_report_model(
    result: MigrationResult,
    timestamp: datetime.datetime | None = None,
    setup_inf_content: str | None = None,
) -> MigrationResultReport:
    """Build a validated MigrationResultReport model from a MigrationResult."""
    ts = timestamp or datetime.datetime.now(datetime.UTC)
    kpis = calculate_kpis(result, setup_inf_content=setup_inf_content)

    artifacts = [
        ArtifactReport(
            rel_path=str(art.rel_path),
            category=art.kind,
            size_bytes=art.size_bytes,
            sha256=art.sha256,
        )
        for art in result.inventory.artifacts
    ]

    traces: list[TraceReport] = []
    todos: list[TodoReport] = []
    if result.transform_result:
        for t in result.transform_result.traces:
            traces.append(
                TraceReport(
                    rule_id=t.rule_id,
                    confidence=t.confidence,
                    target_summary=t.target_summary,
                    doc_ref=t.doc_ref,
                    source_line=t.source_line,
                    source_raw=t.source_raw,
                )
            )
        for td in result.transform_result.todos:
            todos.append(
                TodoReport(
                    raw=td.raw,
                    message=td.message,
                    confidence=td.confidence,
                    line=td.src.line if td.src else None,
                )
            )

    issues = [
        IssueReport(
            severity=i.severity,
            code=i.code,
            message=i.message,
            field=i.field,
        )
        for i in result.issues
    ]

    return MigrationResultReport(
        package_name=kpis.package_name,
        exit_code=result.exit_code,
        success=result.success,
        source_root=str(result.source_root),
        target_root=str(result.target_root) if result.target_root else None,
        tree_hash=result.inventory.tree_hash,
        timestamp=ts.isoformat(),
        lines_dsm=kpis.lines_dsm,
        lines_setup_inf=kpis.lines_setup_inf,
        total_constructs=kpis.total_constructs,
        average_confidence=kpis.average_confidence,
        confidence_color=kpis.confidence_color,
        todo_count=kpis.todo_count,
        todo_quote_pct=kpis.todo_quote_pct,
        error_count=kpis.error_count,
        warning_count=kpis.warning_count,
        artifacts=artifacts,
        traces=traces,
        todos=todos,
        issues=issues,
    )


def get_migration_result_json_schema() -> dict[str, Any]:
    """Return JSON Schema for MigrationResultReport."""
    return MigrationResultReport.model_json_schema()
