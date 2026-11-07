"""Resource-root resolution tests (T-100 packaging prerequisite).

Dev mode must resolve to the repository root so that ``assets/`` and
``rules/`` are found; the frozen-mode branch is exercised by the real
PyInstaller build (packaging/build.ps1 smoke test, AK-5).
"""

from pathlib import Path

from pytest import MonkeyPatch

from dsm2emp._resources import resource_root
from dsm2emp.ai.prompts import PROMPTS_DIR, SCHEMAS_DIR
from dsm2emp.report.render_html import TEMPLATE_PATH
from dsm2emp.rules.loader import get_default_rules_path


def test_resource_root_is_repo_root_in_dev_mode() -> None:
    root = resource_root()
    assert root == Path(__file__).resolve().parents[1]
    assert (root / "assets").is_dir()
    assert (root / "rules").is_dir()


def test_bundled_assets_resolve() -> None:
    assert (PROMPTS_DIR / "translate_fragment.md.j2").is_file()
    assert (SCHEMAS_DIR / "translation.schema.json").is_file()
    assert TEMPLATE_PATH.is_file()


def test_default_rules_path_falls_back_to_resource_root(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Without rules/ in CWD the loader falls back to the resource root."""
    monkeypatch.chdir(tmp_path)
    resolved = get_default_rules_path()
    assert resolved.is_file()
    assert resolved.name == "dsm_to_empirum.yaml"
    assert resolved.parent == resource_root() / "rules"
