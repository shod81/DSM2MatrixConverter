"""AI subsystem package for DSM2Empirum (Task T-060)."""

from dsm2emp.ai.config import AiConfig, get_api_key, set_api_key
from dsm2emp.ai.factory import create_provider, estimate_run_cost
from dsm2emp.ai.openrouter import OpenRouterProvider
from dsm2emp.ai.pipeline import AiPipeline, AiPipelineResult
from dsm2emp.ai.provider import CompletionRequest, CompletionResponse, LlmProvider
from dsm2emp.ai.zai import ZaiProvider

__all__ = [
    "AiConfig",
    "get_api_key",
    "set_api_key",
    "create_provider",
    "estimate_run_cost",
    "AiPipeline",
    "AiPipelineResult",
    "CompletionRequest",
    "CompletionResponse",
    "LlmProvider",
    "OpenRouterProvider",
    "ZaiProvider",
]
