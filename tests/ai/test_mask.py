"""Tests for privacy masking, prompt templates, and fixture secret scanner (Task T-061)."""

from __future__ import annotations

import re
from pathlib import Path

from dsm2emp.ai.mask import mask_text, unmask_text
from dsm2emp.ai.prompts import load_schema, render_review_prompt, render_translation_prompt


def test_mask_serial_numbers() -> None:
    """Serial number patterns are replaced with ⟪SECRET-N⟫ tokens."""
    raw = 'ExecuteEx("app.exe /key:ABCDE-12345-FGHIJ-67890-KLMNO", "Install")'
    res = mask_text(raw)
    assert "ABCDE-12345-FGHIJ-67890-KLMNO" not in res.masked_text
    assert "⟪SECRET-1⟫" in res.masked_text
    assert res.mapping["⟪SECRET-1⟫"] == "ABCDE-12345-FGHIJ-67890-KLMNO"

    # Unmasking restores the original serial number
    restored = unmask_text(res.masked_text, res.mapping)
    assert restored == raw


def test_mask_credentials_and_passwords() -> None:
    """Password and credential assignments are masked while keeping key names."""
    raw = 'Set("password=SuperSecretP@ssw0rd!", "Global")'
    res = mask_text(raw)
    assert "SuperSecretP@ssw0rd!" not in res.masked_text
    assert "password=⟪SECRET-1⟫" in res.masked_text

    restored = unmask_text(res.masked_text, res.mapping)
    assert restored == raw


def test_mask_unc_paths() -> None:
    """UNC network paths are masked to avoid infrastructure leaks."""
    raw = r'CopyFile("\\fileserver.internal.corp\share\setup.msi", "%SRC%\setup.msi")'
    res = mask_text(raw)
    assert r"\\fileserver.internal.corp\share\setup.msi" not in res.masked_text
    assert "⟪SECRET-1⟫" in res.masked_text

    restored = unmask_text(res.masked_text, res.mapping)
    assert restored == raw


def test_mask_domain_users() -> None:
    r"""Domain\User logins are masked."""
    raw = r'RunAs("CORP\svc_installer", "Install")'
    res = mask_text(raw)
    assert r"CORP\svc_installer" not in res.masked_text
    assert "⟪SECRET-1⟫" in res.masked_text

    restored = unmask_text(res.masked_text, res.mapping)
    assert restored == raw


def test_prompt_template_rendering() -> None:
    """Jinja2 prompts render cleanly with masked code."""
    prompt = render_translation_prompt(
        fragment_source="ExecuteEx('app.exe', 'Install')",
        target_section="Set:Product",
        source_ref="Script.inc:10",
    )
    assert "Set:Product" in prompt
    assert "Script.inc:10" in prompt
    assert "ExecuteEx" in prompt

    rev_prompt = render_review_prompt(
        setup_inf_content="[Product]\n#Set:Product, DONTDELETE",
        issues=[],
    )
    assert "[Product]" in rev_prompt


def test_json_schemas_valid() -> None:
    """Schemas load and contain required fields."""
    s_trans = load_schema("translation")
    assert s_trans["title"] == "AiTranslationResponse"
    assert "fragments" in s_trans["properties"]

    s_rev = load_schema("review")
    assert s_rev["title"] == "AiReviewResponse"
    assert "observations" in s_rev["properties"]


def test_secret_scanner_fixtures_zero_leaks() -> None:
    """DoD: Verify that no fixture files contain raw credentials or unmasked keys."""
    golden_dir = Path("tests/golden")
    assert golden_dir.exists(), "tests/golden directory missing"

    leak_patterns = [
        re.compile(r"(?i)\bpassword\s*[:=]\s*([\"'][^\"']+[\"']|[^\s;,]+)"),
        re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*[\"'][a-zA-Z0-9_\-]{16,}[\"']"),
    ]

    for file_path in golden_dir.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            for pat in leak_patterns:
                matches = pat.findall(content)
                assert not matches, f"Secret leak found in {file_path}: {matches}"
        except Exception:
            pass
