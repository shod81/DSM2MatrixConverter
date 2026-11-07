"""Syntax highlighter for Empirum Setup.inf files in PySide6 GUI."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument


class SetupInfHighlighter(QSyntaxHighlighter):
    """Highlighter providing color coding for Empirum Setup.inf files."""

    def __init__(self, parent: QTextDocument) -> None:
        super().__init__(parent)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._init_rules()

    def _init_rules(self) -> None:
        # 1. Keys (key=value) -> Warm yellow
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#fde047"))
        self._rules.append((QRegularExpression(r"^\s*[^=;\r\n]+(?=\s*=)"), key_format))

        # 2. Commands / Keywords -> Soft Indigo / Sky Blue
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#818cf8"))
        keyword_format.setFontWeight(QFont.Weight.DemiBold)
        keywords = [
            "Call",
            "ExecuteEx",
            "Set",
            "If",
            "Else",
            "EndIf",
            "Abort",
            "Exit",
            "Ask",
            "Sleep",
            "Del",
            "Copy",
            "MD",
            "RD",
            "RegModify",
            "RegModifyDWord",
            "RegModifyQWord",
            "RegModifyMultiSZ",
            "RegValue",
            "Reg",
            "ErrorLevel",
            "DoesFileExist",
            "DoesRegKeyExist",
        ]
        pattern = r"\b(" + "|".join(keywords) + r")\b"
        self._rules.append(
            (
                QRegularExpression(pattern, QRegularExpression.PatternOption.CaseInsensitiveOption),
                keyword_format,
            )
        )

        # 3. Strings ("..." or '...') -> Soft green
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#4ade80"))
        self._rules.append((QRegularExpression(r'"[^"\r\n]*"'), string_format))
        self._rules.append((QRegularExpression(r"'[^'\r\n]*'"), string_format))

        # 4. Variables (%Var% or %Src%) -> Amber / Orange
        var_format = QTextCharFormat()
        var_format.setForeground(QColor("#fb923c"))
        var_format.setFontWeight(QFont.Weight.Medium)
        self._rules.append((QRegularExpression(r"%[A-Za-z0-9_.\-]+%"), var_format))

        # 5. Sections [SectionName] -> Bright Cyan bold
        section_format = QTextCharFormat()
        section_format.setForeground(QColor("#38bdf8"))
        section_format.setFontWeight(QFont.Weight.Bold)
        self._rules.append((QRegularExpression(r"^\s*\[[^\]\r\n]+\]"), section_format))

        # 6. Comments (;... or Rem ...) -> Muted Slate Gray
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#64748b"))
        comment_format.setFontItalic(True)
        self._rules.append((QRegularExpression(r";.*$"), comment_format))
        self._rules.append(
            (
                QRegularExpression(
                    r"\bRem\b.*$", QRegularExpression.PatternOption.CaseInsensitiveOption
                ),
                comment_format,
            )
        )

        # 7. High-priority TODOs (Rem TODO: ...) -> Rose / Alert Red bold
        todo_format = QTextCharFormat()
        todo_format.setForeground(QColor("#f43f5e"))
        todo_format.setFontWeight(QFont.Weight.Bold)
        self._rules.append(
            (
                QRegularExpression(
                    r"\bRem\s+TODO:.*$", QRegularExpression.PatternOption.CaseInsensitiveOption
                ),
                todo_format,
            )
        )

    def highlightBlock(self, text: str) -> None:
        """Apply formatting rules sequentially across block."""
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
