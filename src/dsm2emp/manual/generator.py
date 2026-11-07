"""PDF generator for Empirum software package manuals using ReportLab."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from dsm2emp.manual.model import PackageManualInfo


class NumberedCanvas(canvas.Canvas):  # type: ignore[misc]
    """Two-pass canvas to dynamically compute and render total page count."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_footer(num_pages)
            super().showPage()
        super().save()

    def draw_page_footer(self, page_count: int) -> None:
        self.saveState()
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)
        # 18mm margins on A4 (width = 210mm)
        left = 18 * mm
        right = 210 * mm - 18 * mm
        y_line = 14 * mm
        self.line(left, y_line, right, y_line)

        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(left, 9 * mm, "Matrix42 Empirum • Paket-Handbuch (DSM2Empirum Converter)")
        page_str = f"Seite {self._pageNumber} von {page_count}"
        self.drawRightString(right, 9 * mm, page_str)
        self.restoreState()


def _format_size(size_bytes: int) -> str:
    """Format bytes into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def generate_manual_pdf(info: PackageManualInfo, output_path: Path) -> Path:
    """Generate a comprehensive, stylized package manual PDF document."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
    )

    base_styles = getSampleStyleSheet()

    # Custom styles
    primary_color = colors.HexColor("#004B87")  # Matrix42 corporate blue
    dark_slate = colors.HexColor("#1E293B")
    body_color = colors.HexColor("#334155")

    title_kicker_style = ParagraphStyle(
        "Kicker",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0284C7"),
        textTransform="uppercase",
    )

    title_style = ParagraphStyle(
        "PackageTitle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=primary_color,
    )

    subtitle_style = ParagraphStyle(
        "PackageSubtitle",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748B"),
    )

    section_heading_style = ParagraphStyle(
        "SectionHeading",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=primary_color,
        spaceBefore=8,
        spaceAfter=4,
    )

    body_style = ParagraphStyle(
        "BodyDark",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=body_color,
    )

    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    )

    table_cell_bold_style = ParagraphStyle(
        "TableCellBold",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=dark_slate,
    )

    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=body_color,
    )

    code_style = ParagraphStyle(
        "CodeText",
        parent=base_styles["Normal"],
        fontName="Courier",
        fontSize=7.5,
        leading=9.5,
        textColor=dark_slate,
    )

    story: list[Any] = []

    # 1. Header Banner
    story.append(Paragraph("MATRIX42 EMPIRUM • SOFTWAREPAKET-HANDBUCH", title_kicker_style))
    story.append(Spacer(1, 2 * mm))
    title_markup = (
        f"{html.escape(info.product_name)} "
        f"<font size=12 color='#64748B'>v{html.escape(info.version)}</font>"
    )
    story.append(Paragraph(title_markup, title_style))
    story.append(Spacer(1, 1 * mm))
    timestamp_str = info.conversion_timestamp.strftime("%d.%m.%Y, %H:%M:%S Uhr")
    story.append(
        Paragraph(
            f"Hersteller: <b>{html.escape(info.manufacturer)}</b> • "
            f"Konvertiert am: <b>{html.escape(timestamp_str)}</b>",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceAfter=10))

    # 2. Key Highlights Overview Table (2 columns, 6 rows)
    overview_data = [
        [
            Paragraph("<b>Produktname</b>", table_cell_bold_style),
            Paragraph(html.escape(info.product_name), table_cell_style),
            Paragraph("<b>Hersteller</b>", table_cell_bold_style),
            Paragraph(html.escape(info.manufacturer), table_cell_style),
        ],
        [
            Paragraph("<b>Paket-Version</b>", table_cell_bold_style),
            Paragraph(html.escape(info.version), table_cell_style),
            Paragraph("<b>Paket-Typ</b>", table_cell_bold_style),
            Paragraph(html.escape(info.package_type), table_cell_style),
        ],
        [
            Paragraph("<b>Silent-Parameter</b>", table_cell_bold_style),
            Paragraph(
                f"<font color='#004B87'><b>{html.escape(info.silent_parameters)}</b></font>",
                table_cell_style,
            ),
            Paragraph("<b>Konvertiert am</b>", table_cell_bold_style),
            Paragraph(html.escape(timestamp_str), table_cell_style),
        ],
    ]

    overview_table = Table(
        overview_data,
        colWidths=[35 * mm, 52 * mm, 35 * mm, 52 * mm],
    )
    overview_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(overview_table)
    story.append(Spacer(1, 6 * mm))

    # 3. Kurzbeschreibung des Pakets
    story.append(Paragraph("1. Kurzbeschreibung des Pakets", section_heading_style))
    story.append(
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=6)
    )
    for para in info.description.split("\n\n"):
        clean_p = para.strip()
        if clean_p:
            story.append(Paragraph(html.escape(clean_p), body_style))
            story.append(Spacer(1, 2.5 * mm))

    story.append(Spacer(1, 3 * mm))

    # 4. Kurzbeschreibung der Basisparameter des Pakets
    story.append(Paragraph("2. Basisparameter des Softwarepakets", section_heading_style))
    story.append(
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=6)
    )

    params_data = [
        [
            Paragraph("Parameter", table_header_style),
            Paragraph("Wert / Beschreibung", table_header_style),
        ]
    ]

    for key, val in info.basic_parameters.items():
        params_data.append(
            [
                Paragraph(html.escape(key), table_cell_bold_style),
                Paragraph(html.escape(str(val)), table_cell_style),
            ]
        )

    params_table = Table(params_data, colWidths=[60 * mm, 114 * mm])
    params_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), primary_color),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(params_table)
    story.append(Spacer(1, 6 * mm))

    # 5. Enthaltene Payload-Dateien (falls vorhanden)
    if info.payload_files:
        payload_story: list[Any] = []
        payload_story.append(
            Paragraph("3. Enthaltene Payload-Dateien (Files/)", section_heading_style)
        )
        payload_story.append(
            HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=6)
        )

        files_data = [
            [
                Paragraph("Dateiname", table_header_style),
                Paragraph("Größe", table_header_style),
                Paragraph("SHA-256 Prüfsumme", table_header_style),
            ]
        ]
        for name, size_bytes, sha in info.payload_files:
            clean_sha = sha.strip()
            if len(clean_sha) == 64 and "<br/>" not in clean_sha:
                formatted_sha = f"{html.escape(clean_sha[:32])}<br/>{html.escape(clean_sha[32:])}"
            elif len(clean_sha) > 32 and "<br/>" not in clean_sha and " " not in clean_sha:
                formatted_sha = f"{html.escape(clean_sha[:32])}<br/>{html.escape(clean_sha[32:])}"
            else:
                formatted_sha = html.escape(clean_sha)
            files_data.append(
                [
                    Paragraph(html.escape(name), table_cell_bold_style),
                    Paragraph(_format_size(size_bytes), table_cell_style),
                    Paragraph(formatted_sha, code_style),
                ]
            )

        files_table = Table(files_data, colWidths=[65 * mm, 25 * mm, 84 * mm])
        files_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), primary_color),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F8FAFC")],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        payload_story.append(files_table)
        payload_story.append(Spacer(1, 6 * mm))
        story.append(KeepTogether(payload_story))

    # 6. Ausgeführte Installationsbefehle (falls vorhanden)
    if info.command_lines:
        cmd_story: list[Any] = []
        cmd_story.append(
            Paragraph("4. Ausgeführte Installationsbefehle (Setup.inf)", section_heading_style)
        )
        cmd_story.append(
            HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=6)
        )

        for cmd in info.command_lines:
            cmd_data = [[Paragraph(f"<code>{html.escape(cmd)}</code>", code_style)]]
            t = Table(cmd_data, colWidths=[174 * mm])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            cmd_story.append(t)
            cmd_story.append(Spacer(1, 2 * mm))

        story.append(KeepTogether(cmd_story))

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    return output_path
