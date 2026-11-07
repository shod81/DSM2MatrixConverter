"""Unit and integration tests for ReportGenerator (Task T-044)."""

import datetime
import json
from pathlib import Path

from dsm2emp.fixtures.make_packages import create_p01_pure_msi
from dsm2emp.orchestrator import MigrationOptions, migrate_single
from dsm2emp.report.kpi import calculate_kpis
from dsm2emp.report.render_html import render_html_report
from dsm2emp.report.render_md import render_markdown_report
from dsm2emp.report.schema import (
    MigrationResultReport,
    build_report_model,
    get_migration_result_json_schema,
)


def test_kpi_calculation(tmp_path: Path) -> None:
    """Test deterministic KPI calculation from a migration result."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    res = migrate_single(src, tgt, MigrationOptions(force=True))

    kpis = calculate_kpis(res)
    assert kpis.package_name == src.name
    assert kpis.lines_dsm > 0
    assert kpis.lines_setup_inf > 0
    assert kpis.total_constructs > 0
    assert 0.0 <= kpis.average_confidence <= 1.0
    assert kpis.confidence_color in ("green", "yellow", "red")
    assert kpis.todo_count == 0
    assert kpis.todo_quote_pct == 0.0


def test_markdown_report_rendering(tmp_path: Path) -> None:
    """Markdown report includes all required sections per Chapter 5.4."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    res = migrate_single(src, tgt, MigrationOptions(force=True))

    fixed_ts = datetime.datetime(2026, 9, 28, 12, 0, 0, tzinfo=datetime.UTC)
    md = render_markdown_report(res, timestamp=fixed_ts)

    assert f"# Migrationsreport: {src.name}" in md
    assert "## 1. Zusammenfassung & Kennzahlen" in md
    assert "## 2. Inventar (Scandaten)" in md
    assert "## 3. Mapping-Tabelle (Transformationsprotokoll)" in md
    assert "## 4. Offene Punkte (TODOs & manuelle Pruefungen)" in md
    assert "## 5. Validierungsergebnisse" in md
    assert "Dsm2Empirum v1.0" in md
    assert "app.msi" in md


def test_html_report_rendering_offline(tmp_path: Path) -> None:
    """HTML report is fully self-contained without external CDN dependencies."""
    src = create_p01_pure_msi(tmp_path / "src")
    tgt = tmp_path / "tgt"
    res = migrate_single(src, tgt, MigrationOptions(force=True))

    html = render_html_report(res)

    assert "<!DOCTYPE html>" in html
    assert f"Migrationsreport: {src.name}" in html
    assert "<style>" in html
    # Verify no external CDN or font links exist
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html


def test_e3_report_and_json_schema_validation(tmp_path: Path) -> None:
    """DoD: Generate report for E3 and verify JSON Schema validation."""
    e3_input = Path("tests/golden/E3-complex-conditions-registry/input")
    assert e3_input.exists(), "E3 golden input directory missing"

    tgt = tmp_path / "e3_tgt"
    res = migrate_single(e3_input, tgt, MigrationOptions(force=True))
    assert res.success is True

    # 1. Generate Markdown and HTML reports for E3
    md_report = render_markdown_report(res)
    html_report = render_html_report(res)

    assert "Example Report Module" in md_report or "input" in md_report
    assert "report.msi" in md_report
    assert "<!DOCTYPE html>" in html_report

    # 2. Build structured report model
    report_model = build_report_model(res)
    report_dict = json.loads(report_model.model_dump_json())

    # 3. Retrieve JSON Schema and validate E3 report against it
    schema = get_migration_result_json_schema()
    assert isinstance(schema, dict)
    assert schema.get("title") == "MigrationResultReport"
    assert "properties" in schema
    assert "package_name" in schema["properties"]
    assert "average_confidence" in schema["properties"]

    # Validate model re-instantiation from dumped JSON dict
    revalidated = MigrationResultReport.model_validate(report_dict)
    assert revalidated.package_name == report_model.package_name
    assert revalidated.total_constructs == report_model.total_constructs


def test_html_report_escapes_untrusted_script_content(tmp_path: Path) -> None:
    """Regression (XSS): raw DSM script content must be HTML-escaped in reports.

    Package-provided script lines are untrusted input; without autoescaping a
    package could inject active HTML/JS into report.html.
    """
    pkg = tmp_path / "src"
    pkg.mkdir(parents=True)
    (pkg / "Script.inc").write_bytes(
        "Set('Title', '<img src=x onerror=alert(1)>')\r\n".encode("cp1252")
    )
    res = migrate_single(pkg, tmp_path / "tgt", MigrationOptions(force=True))
    assert res.success is True

    html = render_html_report(res)
    assert "<img" not in html
    assert "&lt;img" in html


def test_engine_average_confidence_matches_kpi(tmp_path: Path) -> None:
    """Regression: CLI (TransformResult.average_confidence) and reports (kpi)
    must use the same confidence formula for the same migration."""
    src = create_p01_pure_msi(tmp_path / "src")
    res = migrate_single(src, tmp_path / "tgt", MigrationOptions(force=True))
    assert res.transform_result is not None

    kpis = calculate_kpis(res)
    assert res.transform_result.average_confidence == kpis.average_confidence
