"""Tests for the application icon wiring (window title bar / taskbar)."""

from __future__ import annotations

from dsm2emp.gui.app import app_icon, create_app


def test_app_icon_asset_exists_and_loads(qapp) -> None:  # type: ignore[no-untyped-def]
    """The bundled icon asset resolves in dev mode and loads non-empty."""
    icon = app_icon()
    assert not icon.isNull()
    assert not icon.pixmap(64).isNull()


def test_create_app_sets_window_icon() -> None:
    """create_app configures the QApplication window icon."""
    app = create_app([])
    icon = app.windowIcon()
    assert not icon.isNull()
    pixmap = icon.pixmap(32)
    assert not pixmap.isNull()
    assert pixmap.width() in (32, int(32 * pixmap.devicePixelRatio()))
