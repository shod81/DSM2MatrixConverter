"""Reporting package for migration KPI calculation, Markdown, and HTML report generation."""

from dsm2emp.report.index_page import (
    PackageIndexEntry,
    generate_package_index,
    render_index_html,
    scan_output_directory,
)
from dsm2emp.report.kpi import MigrationKpi, calculate_kpis
from dsm2emp.report.render_html import render_html_report
from dsm2emp.report.render_md import render_markdown_report

__all__ = [
    "MigrationKpi",
    "PackageIndexEntry",
    "calculate_kpis",
    "generate_package_index",
    "render_html_report",
    "render_index_html",
    "render_markdown_report",
    "scan_output_directory",
]
