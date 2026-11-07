"""Loader and validator for DSM-to-Empirum YAML rule catalogs."""

from pathlib import Path
from typing import Any

import yaml

from dsm2emp._resources import resource_root
from dsm2emp.rules.model import RuleDefinition, RuleSet


def get_default_rules_path() -> Path:
    """Find the default rules YAML file path."""
    # 1. Prefer the bundled rules via resource_root()
    candidate = resource_root() / "rules" / "dsm_to_empirum.yaml"
    if candidate.exists():
        return candidate.resolve()

    # 2. Look in working directory rules/ as development fallback
    cwd_path = Path("rules") / "dsm_to_empirum.yaml"
    if cwd_path.exists():
        return cwd_path.resolve()

    return candidate


def load_rules(path: Path | None = None) -> RuleSet:
    """Load rule catalog from YAML file."""
    rules_path = path if path is not None else get_default_rules_path()
    if not rules_path.exists():
        raise FileNotFoundError(f"Rules YAML file not found: {rules_path}")

    raw_text = rules_path.read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(raw_text) or {}

    version = data.get("version", 1)
    meta = data.get("meta", {})
    doc_basis = meta.get("doc_basis", "")
    rules_list: list[RuleDefinition] = []

    for item in data.get("rules", []):
        rules_list.append(RuleDefinition(**item))

    return RuleSet(
        version=version,
        doc_basis=doc_basis,
        rules=rules_list,
    )


def lint_rules(rules: RuleSet) -> list[str]:
    """Validate completeness, uniqueness, and consistency of rule definitions."""
    issues: list[str] = []
    seen_ids: set[str] = set()

    for idx, rule in enumerate(rules.rules, 1):
        # 1. Uniqueness of IDs
        rule_id_upper = rule.id.upper()
        if rule_id_upper in seen_ids:
            issues.append(f"Duplicate rule ID '{rule.id}' at index {idx}")
        seen_ids.add(rule_id_upper)

        # 2. Required fields
        if not rule.id.strip():
            issues.append(f"Rule at index {idx} has an empty ID")
        if not rule.doc_ref.strip():
            issues.append(f"Rule '{rule.id}' is missing doc_ref documentation reference")
        if not rule.description.strip():
            issues.append(f"Rule '{rule.id}' is missing description")
        if not rule.kind.strip():
            issues.append(f"Rule '{rule.id}' is missing kind")

        # 3. Confidence values
        if rule.confidence not in ("high", "medium", "low", "todo"):
            issues.append(f"Rule '{rule.id}' has invalid confidence '{rule.confidence}'")

    return issues
