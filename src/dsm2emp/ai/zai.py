"""Z.ai LLM Provider implementation (Task T-060).

Conforms to Chapter 6.2:
- OpenAI-compatible chat completions API for z.ai
- Strict timeouts and retry with exponential backoff
- Token tracking and cost accounting
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from dsm2emp.ai.config import AiConfig
from dsm2emp.ai.provider import CompletionRequest, CompletionResponse

DEFAULT_ZAI_URL = "https://api.z.ai/v1/chat/completions"


class ZaiProvider:
    """Z.ai API provider implementing LlmProvider."""

    name = "zai"

    def __init__(self, api_key: str, config: AiConfig | None = None) -> None:
        self.api_key = api_key
        self.config = config or AiConfig()
        self.endpoint = self.config.base_url or DEFAULT_ZAI_URL

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost in EUR based on configured token rates."""
        cost = (prompt_tokens / 1000.0) * self.config.price_per_1k_input_tokens + (
            completion_tokens / 1000.0
        ) * self.config.price_per_1k_output_tokens
        return round(cost, 5)

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        """Execute chat completion against Z.ai API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = [
            {"role": "system", "content": req.system_prompt},
            {"role": "user", "content": req.user_prompt},
        ]

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }

        if req.response_format_json:
            payload["response_format"] = {"type": "json_object"}

        retries = 0
        backoff_delay = 1.0

        with httpx.Client(timeout=self.config.timeout_s) as client:
            while True:
                try:
                    resp = client.post(self.endpoint, headers=headers, json=payload)

                    if resp.status_code in (429, 500, 502, 503, 504):
                        if retries < self.config.max_retries:
                            retries += 1
                            time.sleep(backoff_delay)
                            backoff_delay *= 2.0
                            continue
                        resp.raise_for_status()

                    resp.raise_for_status()
                    data = resp.json()

                    choices = data.get("choices", [])
                    if not choices:
                        raise ValueError("Z.ai API returned no completion choices")

                    content = choices[0].get("message", {}).get("content", "")

                    usage = data.get("usage", {})
                    p_tokens = usage.get("prompt_tokens", 0)
                    c_tokens = usage.get("completion_tokens", 0)
                    t_tokens = usage.get("total_tokens", p_tokens + c_tokens)

                    cost = self.estimate_cost(p_tokens, c_tokens)

                    return CompletionResponse(
                        content=content,
                        prompt_tokens=p_tokens,
                        completion_tokens=c_tokens,
                        total_tokens=t_tokens,
                        cost_eur=cost,
                        model=self.config.model,
                        provider=self.name,
                    )

                except httpx.HTTPError as exc:
                    if retries < self.config.max_retries:
                        retries += 1
                        time.sleep(backoff_delay)
                        backoff_delay *= 2.0
                        continue
                    raise RuntimeError(f"Z.ai HTTP Error: {exc}") from exc
