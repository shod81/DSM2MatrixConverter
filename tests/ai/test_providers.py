"""Unit and mock tests for LLM providers and estimation (Task T-060)."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import respx

from dsm2emp.ai.config import AiConfig
from dsm2emp.ai.factory import create_provider, estimate_run_cost
from dsm2emp.ai.openrouter import DEFAULT_OPENROUTER_URL, OpenRouterProvider
from dsm2emp.ai.provider import CompletionRequest
from dsm2emp.ai.zai import DEFAULT_ZAI_URL, ZaiProvider


@respx.mock
def test_openrouter_complete_success() -> None:
    """OpenRouter provider successfully completes and tracks tokens/cost."""
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": '{"result": "success"}',
                }
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }

    route = respx.post(DEFAULT_OPENROUTER_URL).respond(
        status_code=200,
        json=mock_response,
    )

    provider = OpenRouterProvider(api_key="sk-test-key")
    req = CompletionRequest(
        system_prompt="You are a converter.",
        user_prompt="Translate code.",
    )

    resp = provider.complete(req)

    assert route.called
    assert resp.content == '{"result": "success"}'
    assert resp.prompt_tokens == 100
    assert resp.completion_tokens == 50
    assert resp.total_tokens == 150
    assert resp.cost_eur > 0
    assert resp.provider == "openrouter"


@respx.mock
def test_openrouter_retry_on_rate_limit() -> None:
    """Provider retries on HTTP 429 status."""
    mock_success = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }

    # First attempt: 429, Second attempt: 200
    route = respx.post(DEFAULT_OPENROUTER_URL)
    route.side_effect = [
        httpx.Response(429, json={"error": "rate limit"}),
        httpx.Response(200, json=mock_success),
    ]

    cfg = AiConfig(max_retries=2, timeout_s=10.0)
    provider = OpenRouterProvider(api_key="sk-test-key", config=cfg)
    req = CompletionRequest(system_prompt="s", user_prompt="u")

    resp = provider.complete(req)
    assert route.call_count == 2
    assert resp.content == "ok"


@respx.mock
def test_zai_complete_success() -> None:
    """Z.ai provider completes and returns structured output."""
    mock_response = {
        "choices": [{"message": {"content": "zai result"}}],
        "usage": {"prompt_tokens": 80, "completion_tokens": 20},
    }

    route = respx.post(DEFAULT_ZAI_URL).respond(
        status_code=200,
        json=mock_response,
    )

    provider = ZaiProvider(api_key="sk-zai-key")
    req = CompletionRequest(system_prompt="s", user_prompt="u")
    resp = provider.complete(req)

    assert route.called
    assert resp.content == "zai result"
    assert resp.provider == "zai"


def test_create_provider_without_key_stays_disabled() -> None:
    """When enabled is True but key is missing, AI stays off with warning (DoD)."""
    cfg = AiConfig(enabled=True, provider="openrouter")
    with patch("dsm2emp.ai.factory.get_api_key", return_value=(None, None)):
        provider, warning = create_provider(cfg)
        assert provider is None
        assert warning is not None
        assert "W5002" in warning


def test_estimate_run_cost() -> None:
    """Cost estimation correctly projects tokens and EUR cost."""
    cfg = AiConfig(
        provider="openrouter",
        model="claude-3.5-sonnet",
        budget_eur_per_run=1.00,
        max_tokens_per_run=200_000,
    )
    est = estimate_run_cost(cfg, estimated_fragments=10)
    assert est["estimated_fragments"] == 10
    assert est["estimated_tokens"] == 16_000
    assert 0.0 < float(str(est["estimated_cost_eur"])) < 1.0
    assert est["within_budget"] is True
