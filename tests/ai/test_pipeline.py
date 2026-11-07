"""Tests for AI translation pipeline, validation gate (FR-052), and caching (Task T-062)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from dsm2emp.ai.config import AiConfig
from dsm2emp.ai.pipeline import AiPipeline
from dsm2emp.ai.provider import CompletionResponse, LlmProvider
from dsm2emp.ast.nodes import InfDocument, Section, SectionKind
from dsm2emp.parser.ir import IrTodo, SourceRef


def make_dummy_todo(raw: str, line: int = 1) -> IrTodo:
    return IrTodo(
        raw=raw,
        message="Unrecognized construct",
        src=SourceRef(file=Path("Script.inc"), line=line),
        confidence=0.0,
    )


def test_ai_pipeline_valid_suggestion_applied(tmp_path: Path) -> None:
    """Valid AI suggestion passes validator gate and is patched into AST."""
    mock_provider = MagicMock(spec=LlmProvider)
    mock_resp = {
        "fragments": [
            {
                "source_ref": "Script.inc:10",
                "empirum_command": 'Call "%SRC%\\app.exe" /qn',
                "target_section": "Set:Product",
                "confidence": "high",
                "explanation": "Standard silent execution call",
            }
        ]
    }
    mock_provider.complete.return_value = CompletionResponse(
        content=json.dumps(mock_resp),
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        cost_eur=0.001,
        model="claude-3.5-sonnet",
        provider="openrouter",
    )

    doc = InfDocument(
        sections=[
            Section(name="Product", kind=SectionKind.WORK),
            Section(name="Set:Product", kind=SectionKind.WORK),
        ]
    )
    todos = [make_dummy_todo("ExecuteEx('app.exe /qn', 'Install')", line=10)]

    pipeline = AiPipeline(
        provider=mock_provider,
        config=AiConfig(enabled=True),
        cache_dir=tmp_path / "cache",
    )

    doc, result = pipeline.run_pipeline(todos, doc)

    assert result.resolved_count == 1
    assert len(result.remaining_todos) == 0
    assert len(result.applied_traces) == 1
    assert result.applied_traces[0].rule_id == "AI-01"
    assert result.applied_traces[0].target_summary == 'Call "%SRC%\\app.exe" /qn'

    # Check AST patched
    set_prod = doc.get_section("Set:Product")
    assert set_prod is not None
    assert len(set_prod.lines) > 0


def test_ai_pipeline_invalid_suggestion_rejected_fr052(tmp_path: Path) -> None:
    """FR-052: Syntactically broken or unvalidated AI output is strictly rejected."""
    mock_provider = MagicMock(spec=LlmProvider)
    # Output has unbalanced quotes which violates validator F-24 / quoting rules
    mock_resp = {
        "fragments": [
            {
                "source_ref": "Script.inc:20",
                "empirum_command": 'Call "%SRC%\\broken.exe /qn',  # Missing closing quote
                "target_section": "Set:Product",
                "confidence": "high",
                "explanation": "Broken quotes",
            }
        ]
    }
    mock_provider.complete.return_value = CompletionResponse(
        content=json.dumps(mock_resp),
        prompt_tokens=100,
        completion_tokens=30,
        total_tokens=130,
        cost_eur=0.001,
        model="claude-3.5-sonnet",
        provider="openrouter",
    )

    doc = InfDocument(
        sections=[
            Section(name="Product", kind=SectionKind.WORK),
            Section(name="Set:Product", kind=SectionKind.WORK),
        ]
    )
    todo = make_dummy_todo("ExecuteEx('broken.exe /qn', 'Install')", line=20)

    pipeline = AiPipeline(
        provider=mock_provider,
        config=AiConfig(enabled=True),
        cache_dir=tmp_path / "cache",
    )

    doc, result = pipeline.run_pipeline([todo], doc)

    # FR-052 Assertion: Must be rejected and remain as unresolved TODO
    assert result.resolved_count == 0
    assert result.rejected_count == 1
    assert len(result.remaining_todos) == 1
    assert "FR-052" in result.rejection_reasons[0]

    # Verify AST was NOT contaminated
    set_prod = doc.get_section("Set:Product")
    assert set_prod is not None
    assert len(set_prod.lines) == 0


def test_ai_pipeline_caching(tmp_path: Path) -> None:
    """Second identical run retrieves from cache without calling LLM provider."""
    mock_provider = MagicMock(spec=LlmProvider)
    mock_resp = {
        "fragments": [
            {
                "source_ref": "Script.inc:1",
                "empirum_command": "Abort",
                "target_section": "Set:Product",
                "confidence": "medium",
                "explanation": "Abort execution",
            }
        ]
    }
    mock_provider.complete.return_value = CompletionResponse(
        content=json.dumps(mock_resp),
        prompt_tokens=50,
        completion_tokens=20,
        total_tokens=70,
        cost_eur=0.0005,
        model="claude-3.5-sonnet",
        provider="openrouter",
    )

    cache_dir = tmp_path / "ai_cache"
    pipeline = AiPipeline(
        provider=mock_provider,
        config=AiConfig(enabled=True),
        cache_dir=cache_dir,
    )

    doc1 = InfDocument(sections=[Section(name="Set:Product", kind=SectionKind.WORK)])
    todo = make_dummy_todo("ExitProc(1)", line=1)

    # First run: calls provider
    _, res1 = pipeline.run_pipeline([todo], doc1)
    assert res1.resolved_count == 1
    assert res1.cache_hits == 0
    assert mock_provider.complete.call_count == 1

    # Second run: hits cache
    doc2 = InfDocument(sections=[Section(name="Set:Product", kind=SectionKind.WORK)])
    _, res2 = pipeline.run_pipeline([todo], doc2)
    assert res2.resolved_count == 1
    assert res2.cache_hits == 1
    assert mock_provider.complete.call_count == 1  # Provider not called again!


def test_ai_pipeline_budget_limit_stop(tmp_path: Path) -> None:
    """Pipeline halts when budget or token limit is reached."""
    mock_provider = MagicMock(spec=LlmProvider)
    mock_provider.complete.return_value = CompletionResponse(
        content=json.dumps(
            {
                "fragments": [
                    {
                        "source_ref": "Script.inc:1",
                        "empirum_command": "Abort",
                        "target_section": "Set:Product",
                        "confidence": "medium",
                        "explanation": "Abort",
                    }
                ]
            }
        ),
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        cost_eur=0.05,
        model="claude-3.5-sonnet",
        provider="openrouter",
    )

    # Budget is 0.04 EUR, so first call costs 0.05 EUR and exhausts budget
    cfg = AiConfig(enabled=True, budget_eur_per_run=0.04)
    pipeline = AiPipeline(provider=mock_provider, config=cfg, cache_dir=tmp_path / "cache")

    doc = InfDocument(sections=[Section(name="Set:Product", kind=SectionKind.WORK)])
    todos = [
        make_dummy_todo("Command1", line=1),
        make_dummy_todo("Command2", line=2),
    ]

    _, result = pipeline.run_pipeline(todos, doc)

    # First resolved, second stopped due to budget
    assert result.resolved_count == 1
    assert result.budget_exceeded is True
    assert len(result.remaining_todos) == 1
    assert result.remaining_todos[0].raw == "Command2"
