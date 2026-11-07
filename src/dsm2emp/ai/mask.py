"""Privacy masking and de-identification engine for AI interactions (Task T-061).

Conforms to Chapter 6.3 & FR-053:
- Replaces sensitive tokens before any external transmission with placeholder tokens ⟪SECRET-N⟫
- Preserves local mapping dictionary for unmasking returned responses
- Masking targets: Serial numbers, passwords/keys, UNC paths, Domain\\User, GUIDs
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from re import Pattern

# Regex patterns for sensitive data per Chapter 6.3
PATTERNS: list[tuple[str, Pattern[str]]] = [
    # 1. Serial numbers / product keys (e.g. XXXXX-XXXXX-XXXXX-XXXXX-XXXXX or 5-block)
    (
        "SERIAL",
        re.compile(
            r"\b[A-Z0-9]{5}-[A-Z0-9]{5}(?:-[A-Z0-9]{5})*(?:-[A-Z0-9]{5})?\b",
            re.IGNORECASE,
        ),
    ),
    # 2. Passwords / Secrets / API-Keys assignment
    (
        "CREDENTIAL",
        re.compile(
            r"(?i)\b(password|pwd|api_key|apikey|secret|license_key)\s*[:=]\s*([\"'][^\"']+[\"']|[^\s;,]+)",
        ),
    ),
    # 3. UNC Paths (\\server\share\...)
    (
        "UNC",
        re.compile(r"\\\\[a-zA-Z0-9_.\-]+(?:\\[a-zA-Z0-9_.$~ -]+)+"),
    ),
    # 4. Domain\User pattern (e.g. CORP\john.doe, DOMAIN\admin)
    (
        "DOMAIN_USER",
        re.compile(r"\b[a-zA-Z0-9_\-]{2,15}\\[a-zA-Z0-9_.\-]{2,30}\b"),
    ),
]


@dataclass(frozen=True)
class MaskResult:
    """Result of privacy masking operation."""

    masked_text: str
    mapping: dict[str, str] = field(default_factory=dict)  # token -> original_secret

    @property
    def secrets_count(self) -> int:
        return len(self.mapping)


def mask_text(text: str) -> MaskResult:
    """Scan and replace all sensitive patterns with deterministic placeholder tokens."""
    if not text:
        return MaskResult(masked_text="", mapping={})

    mapping: dict[str, str] = {}
    reverse_mapping: dict[str, str] = {}  # original -> token to reuse token if repeated
    counter = 1

    def _replace_match(match: re.Match[str], category: str) -> str:
        nonlocal counter
        full_val = match.group(0)

        # For credentials, preserve key name and only mask the secret value
        if category == "CREDENTIAL" and match.lastindex and match.lastindex >= 2:
            key_name = match.group(1)
            secret_val = match.group(2)
            if secret_val in reverse_mapping:
                token = reverse_mapping[secret_val]
            else:
                token = f"⟪SECRET-{counter}⟫"
                counter += 1
                mapping[token] = secret_val
                reverse_mapping[secret_val] = token

            # Match separator e.g. = or :
            return f"{key_name}={token}"

        if full_val in reverse_mapping:
            return reverse_mapping[full_val]

        token = f"⟪SECRET-{counter}⟫"
        counter += 1
        mapping[token] = full_val
        reverse_mapping[full_val] = token
        return token

    def _make_replacer(category_name: str) -> Callable[[re.Match[str]], str]:
        def _handler(m: re.Match[str]) -> str:
            return _replace_match(m, category_name)

        return _handler

    result_text = text
    for cat, pat in PATTERNS:
        result_text = pat.sub(_make_replacer(cat), result_text)

    return MaskResult(masked_text=result_text, mapping=mapping)


def unmask_text(masked_text: str, mapping: dict[str, str]) -> str:
    """Restore original secrets into returned text from local mapping dictionary."""
    if not masked_text or not mapping:
        return masked_text

    result = masked_text
    for token, original in mapping.items():
        result = result.replace(token, original)

    return result
