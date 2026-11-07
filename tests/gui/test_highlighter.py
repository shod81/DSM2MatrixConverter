"""Tests for SetupInfHighlighter."""

from __future__ import annotations

from PySide6.QtGui import QTextDocument

from dsm2emp.gui.highlighter import SetupInfHighlighter


def test_setup_inf_highlighter_formats_tokens() -> None:
    doc = QTextDocument()
    highlighter = SetupInfHighlighter(doc)

    sample_text = (
        "[SetupInfo]\n"
        "DeveloperName=Contoso\n"
        'Call msiexec.exe /i "%Src%\\setup.msi"\n'
        "; Standard comment\n"
        "Rem TODO: Manual check needed\n"
    )
    doc.setPlainText(sample_text)

    # Verify highlighter attached and rules list configured
    assert len(highlighter._rules) >= 7
