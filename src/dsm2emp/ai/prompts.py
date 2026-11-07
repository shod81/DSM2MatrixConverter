"""Prompt template rendering and JSON schema validation (Task T-061)."""

from __future__ import annotations

import json
from typing import Any

import jinja2

from dsm2emp._resources import resource_root

PROMPTS_DIR = resource_root() / "assets" / "prompts"
SCHEMAS_DIR = resource_root() / "assets" / "schemas"


def render_translation_prompt(
    fragment_source: str,
    target_section: str = "Set:Product",
    source_ref: str = "Script.inc:1",
) -> str:
    """Render the translation prompt using Jinja2."""
    template_file = PROMPTS_DIR / "translate_fragment.md.j2"
    if not template_file.exists():
        raise FileNotFoundError(f"Translation prompt template missing: {template_file}")

    template = jinja2.Template(template_file.read_text(encoding="utf-8"))
    return str(
        template.render(
            fragment_source=fragment_source,
            target_section=target_section,
            source_ref=source_ref,
        )
    )


def render_review_prompt(
    setup_inf_content: str,
    issues: list[Any] | None = None,
) -> str:
    """Render the review prompt using Jinja2."""
    template_file = PROMPTS_DIR / "review_inf.md.j2"
    if not template_file.exists():
        raise FileNotFoundError(f"Review prompt template missing: {template_file}")

    template = jinja2.Template(template_file.read_text(encoding="utf-8"))
    return str(
        template.render(
            setup_inf_content=setup_inf_content,
            issues=issues or [],
        )
    )


def load_schema(schema_name: str) -> dict[str, Any]:
    """Load JSON schema from assets/schemas/."""
    schema_file = SCHEMAS_DIR / f"{schema_name}.schema.json"
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file missing: {schema_file}")
    data = json.loads(schema_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Schema must be a JSON object: {schema_file}")
    return data
