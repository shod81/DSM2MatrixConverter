"""LLM Provider abstraction protocol (Task T-060).

Conforms to Chapter 6.2:
- Protocol LlmProvider
- CompletionRequest & CompletionResponse models
- Token counting and cost calculation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CompletionRequest:
    """Request payload sent to an LLM provider."""

    system_prompt: str
    user_prompt: str
    temperature: float = 0.0
    max_tokens: int = 4096
    response_format_json: bool = True


@dataclass(frozen=True)
class CompletionResponse:
    """Response returned from an LLM completion."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_eur: float
    model: str
    provider: str


@runtime_checkable
class LlmProvider(Protocol):
    """Protocol for LLM service providers."""

    name: str

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        """Execute a completion request synchronously."""
        ...

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost in EUR based on token metrics."""
        ...
