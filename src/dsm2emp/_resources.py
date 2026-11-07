"""Locate bundled read-only resources (assets, rules) in dev and frozen mode.

Dev mode: assets/ and rules/ live at the repository root, two levels above the
``src/`` layout. Frozen mode (PyInstaller onefile, T-100): they are bundled as
datas relative to ``sys._MEIPASS``. Domain code must use :func:`resource_root`
instead of counting ``Path(__file__).parents`` — the level count differs
between both modes and silently breaks under PyInstaller.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    """Return the directory holding ``assets/`` and ``rules/``.

    Returns the ``_MEIPASS`` extraction directory when running from a
    PyInstaller bundle, otherwise the repository root (``src/`` layout).
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if isinstance(meipass, str) and meipass:
            return Path(meipass)
    return Path(__file__).resolve().parents[2]
