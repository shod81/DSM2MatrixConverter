"""Dark modern theme styling for DSM2Empirum GUI (Task T-050)."""

from __future__ import annotations

DARK_STYLE = """
QWidget {
    background-color: #0f172a;
    color: #f8fafc;
    font-family: "Segoe UI", -apple-system, Roboto, sans-serif;
    font-size: 13px;
}

QWizard, QDialog, QMainWindow {
    background-color: #0f172a;
}

QWizard::header {
    background-color: #1e293b;
    color: #38bdf8;
    padding: 12px;
    border-bottom: 1px solid #334155;
    font-weight: bold;
    font-size: 15px;
}

QLabel {
    color: #f8fafc;
}

QLabel#titleLabel {
    font-size: 16px;
    font-weight: bold;
    color: #38bdf8;
    margin-bottom: 8px;
}

QLabel#subtitleLabel {
    font-size: 13px;
    color: #94a3b8;
    margin-bottom: 16px;
}

QLabel#warningLabel {
    background-color: #1e293b;
    border: 1px solid #eab308;
    border-left: 4px solid #eab308;
    border-radius: 4px;
    padding: 8px 12px;
    color: #fde047;
    font-size: 12px;
}

QLabel#infoBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-left: 4px solid #38bdf8;
    border-radius: 4px;
    padding: 8px 12px;
    color: #cbd5e1;
    font-size: 12px;
}

QLineEdit, QComboBox, QSpinBox {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 6px 10px;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #38bdf8;
}

QPushButton {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #334155;
    border-color: #38bdf8;
}

QPushButton:pressed {
    background-color: #0f172a;
}

QPushButton#primaryButton {
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #38bdf8;
    font-weight: bold;
}

QPushButton#primaryButton:hover {
    background-color: #0369a1;
}

QTreeWidget, QTableWidget, QTextEdit, QPlainTextEdit {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 4px;
    gridline-color: #334155;
    alternate-background-color: #162032;
}

QHeaderView::section {
    background-color: #0b1329;
    color: #94a3b8;
    padding: 6px 8px;
    border: 1px solid #334155;
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
}

QProgressBar {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 4px;
    text-align: center;
    color: #f8fafc;
}

QProgressBar::chunk {
    background-color: #0284c7;
    border-radius: 3px;
}

QCheckBox {
    color: #f8fafc;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid #475569;
    background-color: #1e293b;
}

QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
}
"""
