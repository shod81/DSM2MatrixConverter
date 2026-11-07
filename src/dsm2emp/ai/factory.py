"""LLM Provider factory and cost estimation (Task T-060).

Conforms to Chapter 6.2 & 6.5:
- Safe provider instantiation with credential lookup
- Graceful offline fallback when key is absent
- Estimation mode (--ai estimate)
"""

from __future__ import annotations

from dsm2emp.ai.config import AiConfig, get_api_key
from dsm2emp.ai.openrouter import OpenRouterProvider
from dsm2emp.ai.provider import LlmProvider
from dsm2emp.ai.zai import ZaiProvider


def create_provider(config: AiConfig) -> tuple[LlmProvider | None, str | None]:
    """Create an LLM provider based on configuration and keyring credentials.

    Returns:
        (provider_instance, warning_message)
        If no API key found: returns (None, warning_message explaining offline fallback).
    """
    if not config.enabled:
        return None, "KI ist standardmaessig deaktiviert (Offline-Modus)."

    api_key, key_warning = get_api_key(config.provider)

    if not api_key:
        msg = (
            f"W5002: Kein API-Schluessel fuer Provider '{config.provider}' im Windows Credential "
            "Manager hinterlegt (Dsm2Empirum/llm/<provider>). KI-Features bleiben deaktiviert."
        )
        return None, msg

    provider: LlmProvider
    if config.provider == "openrouter":
        provider = OpenRouterProvider(api_key=api_key, config=config)
    elif config.provider == "zai":
        provider = ZaiProvider(api_key=api_key, config=config)
    else:
        return None, f"W5003: Unbekannter KI-Provider '{config.provider}'."

    return provider, key_warning


def estimate_run_cost(
    config: AiConfig,
    estimated_fragments: int,
    avg_prompt_tokens: int = 1200,
    avg_completion_tokens: int = 400,
) -> dict[str, object]:
    """Calculate cost estimate for a migration run (--ai estimate)."""
    total_prompt_tokens = estimated_fragments * avg_prompt_tokens
    total_completion_tokens = estimated_fragments * avg_completion_tokens
    total_tokens = total_prompt_tokens + total_completion_tokens

    cost = (total_prompt_tokens / 1000.0) * config.price_per_1k_input_tokens + (
        total_completion_tokens / 1000.0
    ) * config.price_per_1k_output_tokens

    budget_exceeded = total_tokens > config.max_tokens_per_run or cost > config.budget_eur_per_run

    return {
        "provider": config.provider,
        "model": config.model,
        "estimated_fragments": estimated_fragments,
        "estimated_tokens": total_tokens,
        "estimated_cost_eur": round(cost, 4),
        "budget_limit_eur": config.budget_eur_per_run,
        "token_limit": config.max_tokens_per_run,
        "within_budget": not budget_exceeded,
    }
