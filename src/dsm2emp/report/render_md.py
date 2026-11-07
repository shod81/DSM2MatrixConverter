"""Markdown migration report generator (Task T-044).

Renders comprehensive, human-readable migration audit reports conforming to Chapter 5.4.
"""

from __future__ import annotations

import datetime

from dsm2emp.orchestrator import MigrationResult
from dsm2emp.report.kpi import calculate_kpis


def render_markdown_report(
    result: MigrationResult,
    timestamp: datetime.datetime | None = None,
    setup_inf_content: str | None = None,
) -> str:
    """Render a structured Markdown report from a MigrationResult."""
    ts = timestamp or datetime.datetime.now(datetime.UTC)
    kpis = calculate_kpis(result, setup_inf_content=setup_inf_content)

    if result.success and result.exit_code == 0:
        status_badge = "PASSED"
    elif result.exit_code == 1:
        status_badge = "WARNINGS"
    else:
        status_badge = "FAILED"

    conf_pct = int(kpis.average_confidence * 100)
    target_str = f"`{result.target_root}`" if result.target_root else "N/A"

    lines: list[str] = [
        f"# Migrationsreport: {kpis.package_name}",
        "",
        f"- **Status:** `{status_badge}` (Exit Code {result.exit_code})",
        f"- **Zeitstempel:** {ts.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "- **Tool:** Dsm2Empirum v1.0 (Regelset v1)",
        f"- **Quellordner:** `{result.source_root}`",
        f"- **Zielordner:** {target_str}",
        f"- **Quell-Tree-Hash:** `{result.inventory.tree_hash}`",
        "",
        "## 1. Zusammenfassung & Kennzahlen",
        "",
        "| Kennzahl | Wert |",
        "|:---|:---|",
        f"| DSM-Quellzeilen | {kpis.lines_dsm} |",
        f"| Setup.inf-Zielzeilen | {kpis.lines_setup_inf} |",
        f"| Konstrukte Gesamt | {kpis.total_constructs} |",
        f"| Konfidenz hoch (100%) | {kpis.constructs_high} |",
        f"| Konfidenz mittel (70%) | {kpis.constructs_medium} |",
        f"| Konfidenz niedrig (40%) | {kpis.constructs_low} |",
        f"| Konfidenz Ø | **{conf_pct}%** ({kpis.confidence_color.upper()}) |",
        f"| TODO-Anzahl / Quote | {kpis.todo_count} ({kpis.todo_quote_pct}%) |",
        f"| Validierungsfehler | {kpis.error_count} |",
        f"| Validierungswarnungen | {kpis.warning_count} |",
        "",
        "## 2. Inventar (Scandaten)",
        "",
        "| Relativer Pfad | Typ | Groesse (Bytes) | SHA-256 (Prefix) |",
        "|:---|:---|---:|:---|",
    ]

    for art in result.inventory.artifacts:
        h = art.sha256[:16] + "..." if art.sha256 else "-"
        lines.append(f"| `{art.rel_path}` | {art.kind} | {art.size_bytes} | `{h}` |")

    lines.extend(
        [
            "",
            "## 3. Mapping-Tabelle (Transformationsprotokoll)",
            "",
            "| DSM-Quelle | Zielkonstrukt | Regel-ID | Konfidenz | Referenz |",
            "|:---|:---|:---|:---|:---|",
        ]
    )

    traces = result.transform_result.traces if result.transform_result else []
    if traces:
        for t in traces:
            src_str = f"Z.{t.source_line}: {t.source_raw}" if t.source_line else t.source_raw
            row = (
                f"| `{src_str}` | `{t.target_summary}` | `{t.rule_id}` | "
                f"{t.confidence} | {t.doc_ref} |"
            )
            lines.append(row)
    else:
        lines.append("| *Keine direkten Befehlstransformationen* | - | - | - | - |")

    # TODOs
    todos = result.transform_result.todos if result.transform_result else []
    lines.extend(
        [
            "",
            "## 4. Offene Punkte (TODOs & manuelle Pruefungen)",
            "",
        ]
    )
    if todos:
        lines.extend(
            [
                "| Position | Befehl | Meldung | Konfidenz |",
                "|:---|:---|:---|---:|",
            ]
        )
        for td in todos:
            pos = f"Z.{td.src.line}" if td.src else "-"
            lines.append(f"| {pos} | `{td.raw}` | {td.message} | {td.confidence} |")
    else:
        lines.append("> Keine offenen TODOs – Paket wurde vollstaendig automatisiert migriert.")

    # Validation Details
    lines.extend(
        [
            "",
            "## 5. Validierungsergebnisse",
            "",
        ]
    )
    if result.issues:
        lines.extend(
            [
                "| Schwere | Code | Meldung | Feld |",
                "|:---|:---|:---|:---|",
            ]
        )
        for iss in result.issues:
            fld = iss.field or "-"
            lines.append(f"| {iss.severity.upper()} | `{iss.code}` | {iss.message} | `{fld}` |")
    else:
        lines.append("> Keine Validierungsfehler oder Warnungen (0 Fehler, 0 Warnungen).")

    lines.append("")
    return "\n".join(lines)
