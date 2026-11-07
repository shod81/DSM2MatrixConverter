"""Architecture and security governance guards (Task T-090).

Enforces:
1. Domain package isolation: Core packages never import GUI, network, or process execution.
2. GUI layer isolation: PySide6 is strictly restricted to src/dsm2emp/gui.
3. AI layer isolation: Network client (httpx) is strictly restricted to src/dsm2emp/ai.
4. Quoting guard: src/dsm2emp/emitter/quote.py is the single source of truth for Setup.inf quoting.
5. Secret scanner: Zero hardcoded secrets, private keys, or credentials across the codebase.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_DIR = Path("src/dsm2emp")


def get_all_imports(py_file: Path) -> set[str]:
    """Parse a python file and return all imported module roots."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except Exception as exc:
        raise RuntimeError(f"Failed to parse {py_file}: {exc}") from exc

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    return imported


def test_domain_packages_isolation() -> None:
    """Core domain packages must NOT import GUI, network, or low-level process execution.

    Covered packages:
    - ast
    - parser
    - rules
    - validator
    - emitter
    - reference
    - io
    """
    domain_subdirs = [
        "ast",
        "parser",
        "rules",
        "validator",
        "emitter",
        "reference",
        "io",
    ]

    forbidden_roots = {
        "PySide6",
        "PySide2",
        "PyQt6",
        "PyQt5",
        "tkinter",
        "httpx",
        "requests",
        "urllib.request",
        "subprocess",
        "ctypes",
        "win32com",
    }

    violations: list[str] = []

    for subdir_name in domain_subdirs:
        subdir = SRC_DIR / subdir_name
        if not subdir.exists():
            continue

        for py_path in subdir.rglob("*.py"):
            imports = get_all_imports(py_path)
            for imp in imports:
                root_pkg = imp.split(".")[0]
                if root_pkg in forbidden_roots or imp in forbidden_roots:
                    violations.append(f"{py_path}: imports forbidden module '{imp}'")

    assert not violations, (
        f"Domain isolation violated ({len(violations)} issues):\n"
        + "\n".join(violations)
        + "\nDomain packages must be pure, offline Python without UI or process execution."
    )


def test_gui_package_isolation() -> None:
    """PySide6 must ONLY be imported within src/dsm2emp/gui."""
    violations: list[str] = []

    for py_path in SRC_DIR.rglob("*.py"):
        # Allow only inside src/dsm2emp/gui
        rel = py_path.relative_to(SRC_DIR)
        if rel.parts[0] == "gui":
            continue

        imports = get_all_imports(py_path)
        for imp in imports:
            root_pkg = imp.split(".")[0]
            if root_pkg in {"PySide6", "PySide2", "PyQt6", "PyQt5"}:
                violations.append(f"{py_path}: imports UI library '{imp}' outside gui/")

    assert not violations, "GUI isolation violated:\n" + "\n".join(violations)


def test_ai_package_isolation() -> None:
    """httpx (network library) must ONLY be imported within src/dsm2emp/ai."""
    violations: list[str] = []

    for py_path in SRC_DIR.rglob("*.py"):
        rel = py_path.relative_to(SRC_DIR)
        if rel.parts[0] == "ai":
            continue

        imports = get_all_imports(py_path)
        for imp in imports:
            root_pkg = imp.split(".")[0]
            if root_pkg in {"httpx", "requests"}:
                violations.append(f"{py_path}: imports network client '{imp}' outside ai/")

    assert not violations, "AI/Network isolation violated:\n" + "\n".join(violations)


def test_quoting_single_source_of_truth() -> None:
    """emitter/quote.py is the single source of truth for Setup.inf quoting.

    No non-emitter module may define quoting functions like needs_quotes or q_value.
    """
    quote_py = SRC_DIR / "emitter" / "quote.py"
    assert quote_py.exists(), "quote.py missing"

    violations: list[str] = []
    for py_path in SRC_DIR.rglob("*.py"):
        rel = py_path.relative_to(SRC_DIR)
        if rel.parts[0] == "emitter":
            continue

        content = py_path.read_text(encoding="utf-8")
        if "def needs_quotes(" in content:
            violations.append(f"{py_path}: defines local needs_quotes() instead of using quote.py")
        if "def q_value(" in content:
            violations.append(f"{py_path}: defines local q_value() instead of using quote.py")

    assert not violations, "Quoting single source of truth violated:\n" + "\n".join(violations)


def test_secret_patterns_scan_repository() -> None:
    """Zero hardcoded credentials, secret keys, or private key blocks in codebase."""
    secret_patterns = [
        (
            re.compile(r"-----BEGIN (?:RSA|EC|DSA|OPENSSH|PGP)?\s*PRIVATE KEY-----"),
            "Private Key Block",
        ),
        (
            re.compile(r"\b(?:sk-ant-|sk-or-v1-|sk-proj-)[A-Za-z0-9_\-]{20,}\b"),
            "Live LLM API Key",
        ),
        (
            re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
            "AWS Access Key ID",
        ),
        (
            re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36}\b"),
            "GitHub Token",
        ),
        (
            re.compile(r"\bxox[baprs]-[0-9a-zA-Z]{10,}\b"),
            "Slack Token",
        ),
    ]

    scan_dirs = [
        Path("src"),
        Path("assets"),
        Path("packaging"),
    ]

    violations: list[str] = []

    for d in scan_dirs:
        if not d.exists():
            continue
        for file_path in d.rglob("*"):
            if not file_path.is_file() or file_path.suffix in {".pyc", ".png", ".ico"}:
                continue

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for pattern, desc in secret_patterns:
                match = pattern.search(text)
                if match:
                    violations.append(
                        f"{file_path}: Found potential {desc}: '{match.group(0)[:12]}...'"
                    )

    assert not violations, (
        "Secret pattern guard detected potential secrets in repository:\n" + "\n".join(violations)
    )
