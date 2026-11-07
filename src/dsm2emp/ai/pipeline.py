"""AI translation pipeline with validation, caching, and retry logic (Task T-062).

Conforms to Chapter 6.4, 6.5 & FR-052:
- Strict pipeline: mask -> prompt -> provider -> schema-validate -> parse AST -> validate -> patch
- FR-052: AI suggestions are NEVER adopted unchecked; invalid suggestions are strictly rejected
- Caching: deterministic responses via disk cache (NFR-002)
- Budget stops: aborts AI calls when max_tokens or budget_eur is exceeded
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from dsm2emp.ai.config import AiConfig
from dsm2emp.ai.mask import mask_text, unmask_text
from dsm2emp.ai.prompts import load_schema, render_translation_prompt
from dsm2emp.ai.provider import CompletionRequest, LlmProvider
from dsm2emp.ast.nodes import InfDocument, Section
from dsm2emp.parser.ir import IrTodo
from dsm2emp.rules.model import Confidence, RuleTrace
from dsm2emp.validator.parser import _determine_section_kind, parse_setup_inf
from dsm2emp.validator.rules import validate_fragment


@dataclass
class AiPipelineResult:
    """Outcome of AI translation pipeline execution."""

    resolved_count: int = 0
    remaining_todos: list[IrTodo] = field(default_factory=list)
    applied_traces: list[RuleTrace] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_eur: float = 0.0
    cache_hits: int = 0
    rejected_count: int = 0
    rejection_reasons: list[str] = field(default_factory=list)
    budget_exceeded: bool = False


class AiPipeline:
    """Executes validated AI translation for unresolved DSM constructs."""

    def __init__(
        self,
        provider: LlmProvider,
        config: AiConfig | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.provider = provider
        self.config = config or AiConfig()
        self.cache_dir = cache_dir
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._schema = load_schema("translation")

    def _get_cache_path(self, cache_key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / f"{cache_key}.json"

    def run_pipeline(
        self,
        todos: list[IrTodo],
        document: InfDocument,
    ) -> tuple[InfDocument, AiPipelineResult]:
        """Process unresolved TODO constructs through the AI pipeline."""
        result = AiPipelineResult()
        unresolved: list[IrTodo] = []

        for todo in todos:
            # 1. Budget check
            if (
                result.total_tokens >= self.config.max_tokens_per_run
                or result.total_cost_eur >= self.config.budget_eur_per_run
            ):
                result.budget_exceeded = True
                unresolved.append(todo)
                continue

            # 2. Privacy Masking (FR-053)
            mask_res = mask_text(todo.raw)

            # 3. Render prompt
            source_ref = f"Script.inc:{todo.src.line}" if todo.src else "Script.inc"
            prompt = render_translation_prompt(
                fragment_source=mask_res.masked_text,
                target_section="Set:Product",
                source_ref=source_ref,
            )

            # 4. Check cache for determinism (NFR-002)
            cache_key = hashlib.sha256(f"{self.config.model}:{prompt}".encode()).hexdigest()
            cache_file = self._get_cache_path(cache_key)

            resp_data: dict[str, Any] | None = None
            if cache_file and cache_file.exists():
                try:
                    resp_data = json.loads(cache_file.read_text(encoding="utf-8"))
                    result.cache_hits += 1
                except Exception:
                    resp_data = None

            if resp_data is None:
                # 5. Call LLM Provider
                try:
                    req = CompletionRequest(
                        system_prompt=(
                            "Du bist ein Uebersetzer Ivanti-DSM-eScript -> "
                            "Matrix42-Empirum-Setup.inf. "
                            "Antworte AUSSCHLIESSLICH als JSON gemaess Schema."
                        ),
                        user_prompt=prompt,
                        temperature=0.0,
                        response_format_json=True,
                    )
                    resp = self.provider.complete(req)
                    result.total_tokens += resp.total_tokens
                    result.total_cost_eur += resp.cost_eur

                    resp_data = json.loads(resp.content)
                    if cache_file:
                        cache_file.write_text(
                            json.dumps(resp_data, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                except Exception as exc:
                    result.rejected_count += 1
                    result.rejection_reasons.append(f"Provider/JSON-Fehler bei '{todo.raw}': {exc}")
                    unresolved.append(todo)
                    continue

            # 6. Schema Validation
            try:
                jsonschema.validate(instance=resp_data, schema=self._schema)
            except Exception as s_err:
                result.rejected_count += 1
                result.rejection_reasons.append(f"Schema-Validierungsfehler: {s_err}")
                unresolved.append(todo)
                continue

            # 7. Extract and unmask proposal
            fragments = resp_data.get("fragments", [])
            if not fragments:
                result.rejected_count += 1
                result.rejection_reasons.append(f"Keine Fragmente geliefert fuer '{todo.raw}'")
                unresolved.append(todo)
                continue

            frag = fragments[0]
            masked_cmd = frag.get("empirum_command", "").strip()
            target_sec_name = frag.get("target_section", "Set:Product").strip()
            raw_conf = frag.get("confidence", "medium")
            conf_val: Confidence = raw_conf if raw_conf in ("high", "medium", "low") else "medium"
            explanation = frag.get("explanation", "KI-Uebersetzung")

            final_cmd = unmask_text(masked_cmd, mask_res.mapping)

            # 8. Strict Empirum Validator Check (FR-052)
            # Never accept AI suggestions without passing the validator!
            val_issues = validate_fragment(final_cmd, target_section=target_sec_name)
            errors = [i for i in val_issues if i.severity == "error"]
            if errors:
                err_msgs = "; ".join(f"{e.code}: {e.message}" for e in errors)
                result.rejected_count += 1
                result.rejection_reasons.append(
                    f"FR-052: KI-Vorschlag '{final_cmd}' vom Validator abgelehnt ({err_msgs})"
                )
                unresolved.append(todo)
                continue

            test_inf_text = f"[{target_sec_name}]\n{final_cmd}\n"
            try:
                parsed_test_doc = parse_setup_inf(test_inf_text)
            except Exception as parse_err:
                result.rejected_count += 1
                result.rejection_reasons.append(
                    f"FR-052: KI-Vorschlag '{final_cmd}' ist syntaktisch ungueltig ({parse_err})"
                )
                unresolved.append(todo)
                continue

            # 9. Patch into AST
            target_sec = document.get_section(target_sec_name)
            if not target_sec:
                sec_kind, sec_prefix = _determine_section_kind(target_sec_name)
                target_sec = Section(
                    name=target_sec_name,
                    kind=sec_kind,
                    typed_prefix=sec_prefix,
                )
                document.sections.append(target_sec)

            test_sec = parsed_test_doc.get_section(target_sec_name)
            if test_sec and test_sec.lines:
                for line_node in test_sec.lines:
                    target_sec.lines.append(line_node)

            trace = RuleTrace(
                rule_id="AI-01",
                source_line=todo.src.line if todo.src else 0,
                source_raw=todo.raw,
                confidence=conf_val,
                target_summary=final_cmd,
                doc_ref="KI-Uebersetzung (validiert)",
                notes=[explanation],
            )
            result.applied_traces.append(trace)
            result.resolved_count += 1

        result.remaining_todos = unresolved
        return document, result
