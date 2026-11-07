"""GUI application entry point (Task T-050)."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from dsm2emp._resources import resource_root
from dsm2emp.gui.start_window import StartWindow


def app_icon() -> QIcon:
    """Application icon from the bundled assets (null icon if absent)."""
    return QIcon(str(resource_root() / "assets" / "icon.ico"))


def create_app(argv: Sequence[str] | None = None) -> QApplication:
    """Create and configure QApplication."""
    instance = QApplication.instance()
    if isinstance(instance, QApplication):
        app = instance
    else:
        app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("DSM2Empirum")
    app.setOrganizationName("Matrix42 Migration")
    app.setWindowIcon(app_icon())
    return app


def run_gui(argv: Sequence[str] | None = None) -> int:
    """Run DSM2Empirum GUI application."""
    app = create_app(argv)
    window = StartWindow()
    window.show()
    return app.exec()
