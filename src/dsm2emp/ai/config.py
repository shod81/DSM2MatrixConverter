"""AI configuration and Windows Credential Manager integration (Task T-060).

Conforms to Chapter 6.2 & 6.7:
- Auth: API-Key exclusively from Windows Credential Manager
  keyring target name: 'Dsm2Empirum/llm/<provider>'
- Missing key => AI feature disabled, warning logged, offline mode preserved
- Hard limits: max_tokens_per_run, budget_eur_per_run, max_retries
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

try:
    import keyring
except ImportError:
    keyring = None  # type: ignore[assignment]


KEYRING_SERVICE_PREFIX = "Dsm2Empirum/llm"


@dataclass(frozen=True)
class AiConfig:
    """Configuration for LLM AI translation and review."""

    enabled: bool = False
    provider: Literal["openrouter", "zai"] = "openrouter"
    model: str = "anthropic/claude-3.5-sonnet"
    base_url: str | None = None
    timeout_s: float = 60.0
    max_retries: int = 2
    max_tokens_per_run: int = 200_000
    budget_eur_per_run: float = 1.00
    price_per_1k_input_tokens: float = 0.003
    price_per_1k_output_tokens: float = 0.015


def get_api_key(provider: str) -> tuple[str | None, str | None]:
    """Retrieve API key for provider.

    Returns:
        (api_key, warning_message)
        If key from keyring: warning is None
        If key from env var: warning contains CI notice
        If no key: (None, None)
    """
    service_name = f"{KEYRING_SERVICE_PREFIX}/{provider}"

    # 1. Primary: Windows Credential Manager via keyring
    if keyring is not None:
        try:
            secret = keyring.get_password(service_name, "api_key")
            if secret:
                return secret, None
        except Exception:
            pass

    # 2. CI/Test fallback: Environment variable with warning
    env_var = f"DSM2EMP_{provider.upper()}_API_KEY"
    if env_var in os.environ and os.environ[env_var].strip():
        warning = (
            f"W5001: API-Key fuer '{provider}' wurde aus Umgebungsvariable '{env_var}' "
            "geladen statt aus dem Windows Credential Manager."
        )
        return os.environ[env_var].strip(), warning

    general_env = "DSM2EMP_AI_API_KEY"
    if general_env in os.environ and os.environ[general_env].strip():
        warning = (
            f"W5001: API-Key wurde aus generischer Umgebungsvariable '{general_env}' "
            "geladen statt aus dem Windows Credential Manager."
        )
        return os.environ[general_env].strip(), warning

    return None, None


def set_api_key(provider: str, api_key: str) -> bool:
    """Store API key into Windows Credential Manager."""
    if keyring is None:
        return False
    service_name = f"{KEYRING_SERVICE_PREFIX}/{provider}"
    try:
        keyring.set_password(service_name, "api_key", api_key)
        return True
    except Exception:
        return False
