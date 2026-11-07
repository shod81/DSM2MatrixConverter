"""Locate bundled read-only resources (assets, rules) in dev and frozen mode.

All runtime resources live inside the package under ``dsm2emp/data``. That path
resolves identically in a source checkout, in an installed wheel and in a
PyInstaller onefile bundle, where ``__file__`` points into ``sys._MEIPASS``.

Domain code must use :func:`resource_root` instead of counting
``Path(__file__).parents`` — the level count differs between layouts and
silently breaks under PyInstaller.
"""

from __future__ import annotations

from pathlib import Path


def resource_root() -> Path:
    """Return the directory holding ``assets/``, ``rules/`` and ``reference/``."""
    return Path(__file__).resolve().parent / "data"
