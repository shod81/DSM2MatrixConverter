"""Architecture compliance tests for GUI layer (Task T-050).

Verifies Chapter 5.1 constraints:
- Views only read domain result objects.
- No direct file execution or forbidden process execution in UI view modules.
- Strict separation between GUI (Layer 4) and Domain/Core (Layer 3).
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_gui_views_architecture_cleanliness() -> None:
    """Check that wizard and window view modules do not contain forbidden imports."""
    gui_dir = Path("src/dsm2emp/gui")
    view_files = [
        gui_dir / "start_window.py",
        gui_dir / "batch_window.py",
        gui_dir / "wizard" / "wizard.py",
        gui_dir / "wizard" / "step1_select.py",
        gui_dir / "wizard" / "step2_scan.py",
        gui_dir / "wizard" / "step3_mapping.py",
        gui_dir / "wizard" / "step4_diff.py",
    ]

    forbidden_modules = {
        "subprocess",
        "ctypes",
        "win32com",
        "dsm2emp.parser.escript",
        "dsm2emp.parser.registry",
    }

    for file_path in view_files:
        assert file_path.exists(), f"View file {file_path} missing"
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))

        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)

        violations = imported_modules.intersection(forbidden_modules)
        assert not violations, (
            f"Architecture violation in {file_path.name}: "
            f"Forbidden modules imported: {violations}. "
            f"Views must only read domain result objects per Chapter 5.1."
        )
