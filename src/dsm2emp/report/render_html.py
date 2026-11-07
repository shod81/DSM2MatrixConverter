"""HTML migration report generator using Jinja2 without external assets (Task T-044).

Conforms strictly to Chapter 5.4 with responsive layout and 100% offline capability.
"""

from __future__ import annotations

import datetime

import jinja2

from dsm2emp._resources import resource_root
from dsm2emp.orchestrator import MigrationResult
from dsm2emp.report.kpi import calculate_kpis

# Path to template file in assets/ (repo root in dev, _MEIPASS when frozen)
TEMPLATE_PATH = resource_root() / "assets" / "report_template.html.j2"

# Autoescaping is mandatory: report content includes raw DSM script lines and
# package metadata taken from untrusted package sources (FR-053 / XSS).
_JINJA_ENV = jinja2.Environment(autoescape=True)


def _get_template() -> jinja2.Template:
    """Load report HTML template from assets or fallback."""
    if TEMPLATE_PATH.exists():
        content = TEMPLATE_PATH.read_text(encoding="utf-8")
        return _JINJA_ENV.from_string(content)
    # Built-in fallback template
    fallback = "<html><body><h1>Report: {{ kpis.package_name }}</h1></body></html>"
    return _JINJA_ENV.from_string(fallback)


def render_html_report(
    result: MigrationResult,
    timestamp: datetime.datetime | None = None,
    setup_inf_content: str | None = None,
) -> str:
    """Render self-contained HTML report string for a package migration."""
    ts = timestamp or datetime.datetime.now(datetime.UTC)
    kpis = calculate_kpis(result, setup_inf_content=setup_inf_content)

    if result.exit_code == 0:
        status_class = "passed"
        status_label = "PASSED"
    elif result.exit_code == 1:
        status_class = "warnings"
        status_label = "WARNINGS"
    else:
        status_class = "failed"
        status_label = "FAILED"

    template = _get_template()
    return template.render(
        result=result,
        kpis=kpis,
        status_class=status_class,
        status_label=status_label,
        timestamp_str=ts.strftime("%Y-%m-%d %H:%M:%S UTC"),
    )
