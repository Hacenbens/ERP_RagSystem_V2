"""HybridAgent — runs RAGAgent and SQLAgent in parallel, merges with LLM.

Pipeline:
  1. asyncio.gather(rag_agent.run(), sql_agent.run())  ← parallel
  2a. Both succeed → LLMPort.complete(hybrid_merger_prompt) → HybridResult
  2b. SQL fails   → HybridResult.rag_fallback(rag_result)   ← partial
  2c. RAG fails   → HybridResult.sql_fallback(sql_result)   ← partial
  2d. Both fail   → raise HybridAgentError

Observability:
  HYBRID_SUCCESS_RATE — incremented when both agents succeed and merger runs
  HYBRID_LATENCY      — histogram of end-to-end wall-clock time
  Partial failures are logged at WARNING; HYBRID_PARTIAL_RATE added in TASK 11.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from typing import Any

from src.agents.base_agent import AgentContext, BaseAgent
from src.agents.helpers import parse_llm_json
from src.agents.rag_agent import RAGAgent
from src.agents.sql_agent import SQLAgent
from src.domain.models.hybrid_result import HybridResult
from src.domain.models.rag_result import RAGResult
from src.domain.models.sql_result import SQLResult
from src.domain.ports.llm_port import LLMPort
from src.observability.prometheus_metrics import HYBRID_LATENCY, HYBRID_SUCCESS_RATE
from src.observability.structured_logger import get_logger
from src.prompts.registry import PromptRegistry

logger = get_logger(__name__)


class HybridAgentError(RuntimeError):
    """Raised when both RAGAgent and SQLAgent fail for the same query."""


def _render_hybrid_prompt(
    prompt_text: str,
    query: str,
    rag_result: RAGResult,
    sql_result: SQLResult,
) -> str:
    """Fill {{sql_result_json}}, {{rag_result_json}}, {{masked_query}} placeholders."""
    sql_json = json.dumps(dataclasses.asdict(sql_result), default=str)
    rag_json = json.dumps(dataclasses.asdict(rag_result), default=str)
    return (
        prompt_text
        .replace("{{sql_result_json}}", sql_json)
        .replace("{{rag_result_json}}", rag_json)
        .replace("{{masked_query}}", query)
    )


class HybridAgent(BaseAgent):
    """Run RAG and SQL branches in parallel and synthesise one coherent answer.

    Partial failures are handled gracefully:
    - SQL failure → RAG-only ``HybridResult`` (``rag_only=True``)
    - RAG failure → SQL-only ``HybridResult`` (``sql_only=True``)
    - Both fail   → ``HybridAgentError`` (caller should return HTTP 502)

    When both succeed the merger LLM prompt is called once to produce
    a single ``merged_answer``.  If that LLM call itself fails the result
    falls back to ``rag_fallback`` so the caller always gets a usable answer.
    """

    def __init__(
        self,
        rag_agent: RAGAgent,
        sql_agent: SQLAgent,
        llm: LLMPort,
        registry: PromptRegistry,
    ) -> None:
        self._rag = rag_agent
        self._sql = sql_agent
        self._llm = llm
        self._registry = registry

    async def run(self, query: str, context: AgentContext) -> HybridResult:
        """Execute RAG + SQL in parallel then merge the results."""
        logger.info(
            "hybrid_agent.start",
            tenant_id=context.tenant_id,
            erp_module=context.erp_module,
            trace_id=context.trace_id,
        )
        t0 = time.perf_counter()

        rag_outcome, sql_outcome = await asyncio.gather(
            self._rag.run(query, context),
            self._sql.run(query, context),
            return_exceptions=True,
        )

        rag_ok = isinstance(rag_outcome, RAGResult)
        sql_ok = isinstance(sql_outcome, SQLResult)

        if not rag_ok and not sql_ok:
            logger.error(
                "hybrid_agent.both_failed",
                rag_error=str(rag_outcome),
                sql_error=str(sql_outcome),
                trace_id=context.trace_id,
            )
            raise HybridAgentError(
                f"Both agents failed — RAG: {rag_outcome!r}; SQL: {sql_outcome!r}"
            )

        if not sql_ok:
            logger.warning(
                "hybrid_agent.sql_failed_rag_fallback",
                sql_error=str(sql_outcome),
                trace_id=context.trace_id,
            )
            result = HybridResult.rag_fallback(rag_outcome)  # type: ignore[arg-type]
        elif not rag_ok:
            logger.warning(
                "hybrid_agent.rag_failed_sql_fallback",
                rag_error=str(rag_outcome),
                trace_id=context.trace_id,
            )
            result = HybridResult.sql_fallback(sql_outcome)  # type: ignore[arg-type]
        else:
            result = self._merge(query, rag_outcome, sql_outcome)  # type: ignore[arg-type]
            HYBRID_SUCCESS_RATE.inc()

        latency_s = time.perf_counter() - t0
        HYBRID_LATENCY.observe(latency_s)
        logger.info(
            "hybrid_agent.done",
            is_partial=result.is_partial,
            rag_only=result.rag_only,
            sql_only=result.sql_only,
            latency_ms=round(latency_s * 1000, 1),
            trace_id=context.trace_id,
        )
        return result

    def _merge(
        self,
        query: str,
        rag_result: RAGResult,
        sql_result: SQLResult,
    ) -> HybridResult:
        """Call the merger LLM and parse its JSON output into a HybridResult."""
        pv = self._registry.resolve("hybrid_orchestrator")
        prompt = _render_hybrid_prompt(pv.prompt_text, query, rag_result, sql_result)

        raw = self._llm.complete(
            prompt,
            temperature=pv.parameters.temperature,
            max_tokens=pv.parameters.max_tokens,
        )

        try:
            output: dict[str, Any] = parse_llm_json(raw)
            self._registry.validate_output(pv, output)
        except Exception as exc:
            logger.warning("hybrid_agent.merge_parse_failed", error=str(exc))
            return HybridResult.rag_fallback(rag_result)

        return HybridResult(
            rag_result=rag_result,
            sql_result=sql_result,
            merged_answer=output["merged_answer"],
            sql_contribution=output["sql_contribution"],
            rag_contribution=output["rag_contribution"],
            overall_confidence=float(output["overall_confidence"]),
            contradictions=tuple(output.get("contradictions", [])),
            cited_chunks=tuple(output.get("cited_chunks", [])),
            sql_tables_used=tuple(output.get("sql_tables_used", [])),
        )


__all__ = ["HybridAgent", "HybridAgentError"]
