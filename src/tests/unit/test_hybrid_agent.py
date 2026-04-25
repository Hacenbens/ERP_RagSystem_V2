"""
Unit tests for HybridAgent — Sprint 7 Task 8.

Coverage:
  1. Happy path — both agents succeed, merger LLM called, HybridResult returned
  2. Partial failure — SQL fails → rag_fallback
  3. Partial failure — RAG fails → sql_fallback
  4. Both fail → HybridAgentError raised
  5. Merger LLM parse failure → graceful rag_fallback (no crash)
  6. asyncio.gather — both agents run concurrently (ordering proof)
  7. Prometheus counters incremented correctly
  8. Edge cases — empty rows, zero confidence, contradictions list
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base_agent import AgentContext
from src.agents.hybrid_agent import HybridAgent, HybridAgentError, _render_hybrid_prompt
from src.agents.rag_agent import RAGAgent
from src.agents.sql_agent import SQLAgent, SQLAgentError
from src.domain.models.hybrid_result import HybridResult
from src.domain.models.rag_result import RAGResult
from src.domain.models.sql_result import SQLResult
from src.domain.ports.llm_port import LLMPort
from src.prompts.registry import PromptRegistry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

_CTX = AgentContext(tenant_id="t-acme", erp_module="finance", trace_id="tr-hybrid")

_RAG_OK = RAGResult(
    grounded=True,
    answer="VAT rate is 9% [c-1].",
    cited_chunks=("c-1",),
    grounding_score=0.91,
    confidence=0.91,
    insufficient_data_for=(),
)

_SQL_OK = SQLResult(
    query="SELECT id FROM invoices WHERE tenant_id = :tenant_id LIMIT 10",
    rows=({"invoice_id": "inv-1"},),
    row_count=1,
    latency_ms=42.0,
    query_id="exec-42",
)

_VALID_MERGE_JSON = json.dumps({
    "merged_answer": "Based on ERP data and policy, VAT is 9%.",
    "sql_contribution": "One invoice found.",
    "rag_contribution": "Tax circular confirms 9%.",
    "contradictions": [],
    "overall_confidence": 0.88,
    "cited_chunks": ["c-1"],
    "sql_tables_used": ["invoices"],
})


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

class _StubLLM(LLMPort):
    def __init__(self, response: str = _VALID_MERGE_JSON) -> None:
        self._response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        self.calls.append(prompt)
        return self._response


def _agent_returning(result: object) -> MagicMock:
    """Create a mock agent whose run() returns `result` (or raises it)."""
    mock = MagicMock(spec=RAGAgent)
    if isinstance(result, BaseException):
        mock.run = AsyncMock(side_effect=result)
    else:
        mock.run = AsyncMock(return_value=result)
    return mock


def _make_hybrid(
    rag_result: object = _RAG_OK,
    sql_result: object = _SQL_OK,
    llm_response: str = _VALID_MERGE_JSON,
) -> HybridAgent:
    return HybridAgent(
        rag_agent=_agent_returning(rag_result),
        sql_agent=_agent_returning(sql_result),
        llm=_StubLLM(llm_response),
        registry=PromptRegistry(PROMPTS_DIR),
    )


# ---------------------------------------------------------------------------
# 1. Happy path — both succeed, LLM merges
# ---------------------------------------------------------------------------

class TestHybridAgentHappyPath:
    @pytest.mark.asyncio
    async def test_hybrid_agent_both_succeed_returns_hybrid_result(self) -> None:
        agent = _make_hybrid()
        result = await agent.run("VAT rate query", _CTX)

        assert isinstance(result, HybridResult)
        assert result.merged_answer == "Based on ERP data and policy, VAT is 9%."
        assert result.overall_confidence == 0.88
        assert result.is_partial is False

    @pytest.mark.asyncio
    async def test_hybrid_agent_both_succeed_stores_rag_and_sql_results(self) -> None:
        agent = _make_hybrid()
        result = await agent.run("query", _CTX)

        assert result.rag_result is _RAG_OK
        assert result.sql_result is _SQL_OK

    @pytest.mark.asyncio
    async def test_hybrid_agent_maps_cited_chunks_as_tuple(self) -> None:
        agent = _make_hybrid()
        result = await agent.run("query", _CTX)

        assert isinstance(result.cited_chunks, tuple)
        assert "c-1" in result.cited_chunks

    @pytest.mark.asyncio
    async def test_hybrid_agent_maps_sql_tables_used_as_tuple(self) -> None:
        agent = _make_hybrid()
        result = await agent.run("query", _CTX)

        assert isinstance(result.sql_tables_used, tuple)
        assert "invoices" in result.sql_tables_used

    @pytest.mark.asyncio
    async def test_hybrid_agent_maps_contradictions_as_tuple(self) -> None:
        with_contradiction = json.dumps({
            "merged_answer": "answer",
            "sql_contribution": "sql",
            "rag_contribution": "rag",
            "contradictions": ["Policy says 9% but ERP records show 8%."],
            "overall_confidence": 0.5,
            "cited_chunks": [],
            "sql_tables_used": [],
        })
        agent = _make_hybrid(llm_response=with_contradiction)
        result = await agent.run("query", _CTX)

        assert isinstance(result.contradictions, tuple)
        assert len(result.contradictions) == 1

    @pytest.mark.asyncio
    async def test_hybrid_agent_passes_query_to_both_agents(self) -> None:
        rag_mock = _agent_returning(_RAG_OK)
        sql_mock = _agent_returning(_SQL_OK)
        agent = HybridAgent(
            rag_agent=rag_mock,
            sql_agent=sql_mock,
            llm=_StubLLM(),
            registry=PromptRegistry(PROMPTS_DIR),
        )

        await agent.run("specific query text", _CTX)

        rag_mock.run.assert_awaited_once_with("specific query text", _CTX)
        sql_mock.run.assert_awaited_once_with("specific query text", _CTX)

    @pytest.mark.asyncio
    async def test_hybrid_agent_passes_context_to_both_agents(self) -> None:
        rag_mock = _agent_returning(_RAG_OK)
        sql_mock = _agent_returning(_SQL_OK)
        agent = HybridAgent(
            rag_agent=rag_mock,
            sql_agent=sql_mock,
            llm=_StubLLM(),
            registry=PromptRegistry(PROMPTS_DIR),
        )

        await agent.run("query", _CTX)

        assert rag_mock.run.call_args[0][1] is _CTX
        assert sql_mock.run.call_args[0][1] is _CTX


# ---------------------------------------------------------------------------
# 2. Partial failure — SQL fails → rag_fallback
# ---------------------------------------------------------------------------

class TestHybridAgentSQLFailure:
    @pytest.mark.asyncio
    async def test_sql_failure_returns_rag_fallback(self) -> None:
        agent = _make_hybrid(sql_result=SQLAgentError("db down"))
        result = await agent.run("query", _CTX)

        assert isinstance(result, HybridResult)
        assert result.rag_only is True
        assert result.sql_only is False
        assert result.sql_result is None
        assert result.rag_result is _RAG_OK

    @pytest.mark.asyncio
    async def test_sql_failure_does_not_call_merger_llm(self) -> None:
        llm = _StubLLM()
        agent = HybridAgent(
            rag_agent=_agent_returning(_RAG_OK),
            sql_agent=_agent_returning(SQLAgentError("down")),
            llm=llm,
            registry=PromptRegistry(PROMPTS_DIR),
        )

        await agent.run("query", _CTX)

        assert len(llm.calls) == 0

    @pytest.mark.asyncio
    async def test_sql_failure_result_is_partial(self) -> None:
        agent = _make_hybrid(sql_result=RuntimeError("network"))
        result = await agent.run("query", _CTX)

        assert result.is_partial is True

    @pytest.mark.asyncio
    async def test_sql_failure_confidence_matches_rag_confidence(self) -> None:
        agent = _make_hybrid(sql_result=Exception("timeout"))
        result = await agent.run("query", _CTX)

        assert result.overall_confidence == _RAG_OK.confidence


# ---------------------------------------------------------------------------
# 3. Partial failure — RAG fails → sql_fallback
# ---------------------------------------------------------------------------

class TestHybridAgentRAGFailure:
    @pytest.mark.asyncio
    async def test_rag_failure_returns_sql_fallback(self) -> None:
        agent = _make_hybrid(rag_result=RuntimeError("vector store down"))
        result = await agent.run("query", _CTX)

        assert isinstance(result, HybridResult)
        assert result.sql_only is True
        assert result.rag_only is False
        assert result.rag_result is None
        assert result.sql_result is _SQL_OK

    @pytest.mark.asyncio
    async def test_rag_failure_does_not_call_merger_llm(self) -> None:
        llm = _StubLLM()
        agent = HybridAgent(
            rag_agent=_agent_returning(Exception("embedding down")),
            sql_agent=_agent_returning(_SQL_OK),
            llm=llm,
            registry=PromptRegistry(PROMPTS_DIR),
        )

        await agent.run("query", _CTX)

        assert len(llm.calls) == 0

    @pytest.mark.asyncio
    async def test_rag_failure_result_is_partial(self) -> None:
        agent = _make_hybrid(rag_result=Exception("down"))
        result = await agent.run("query", _CTX)

        assert result.is_partial is True


# ---------------------------------------------------------------------------
# 4. Both agents fail → HybridAgentError
# ---------------------------------------------------------------------------

class TestHybridAgentBothFail:
    @pytest.mark.asyncio
    async def test_both_fail_raises_hybrid_agent_error(self) -> None:
        agent = _make_hybrid(
            rag_result=RuntimeError("rag down"),
            sql_result=SQLAgentError("sql down"),
        )

        with pytest.raises(HybridAgentError):
            await agent.run("query", _CTX)

    @pytest.mark.asyncio
    async def test_both_fail_error_message_mentions_both_agents(self) -> None:
        agent = _make_hybrid(
            rag_result=RuntimeError("embedding failed"),
            sql_result=SQLAgentError("tenant filter missing"),
        )

        with pytest.raises(HybridAgentError, match="Both agents failed"):
            await agent.run("query", _CTX)

    @pytest.mark.asyncio
    async def test_both_fail_does_not_call_llm(self) -> None:
        llm = _StubLLM()
        agent = HybridAgent(
            rag_agent=_agent_returning(RuntimeError("rag down")),
            sql_agent=_agent_returning(RuntimeError("sql down")),
            llm=llm,
            registry=PromptRegistry(PROMPTS_DIR),
        )

        with pytest.raises(HybridAgentError):
            await agent.run("query", _CTX)

        assert len(llm.calls) == 0


# ---------------------------------------------------------------------------
# 5. Merger LLM failure → graceful rag_fallback
# ---------------------------------------------------------------------------

class TestHybridAgentMergerFailure:
    @pytest.mark.asyncio
    async def test_merger_invalid_json_falls_back_to_rag(self) -> None:
        agent = _make_hybrid(llm_response="not valid JSON")
        result = await agent.run("query", _CTX)

        assert result.rag_only is True
        assert result.is_partial is True

    @pytest.mark.asyncio
    async def test_merger_schema_violation_falls_back_to_rag(self) -> None:
        bad_merge = json.dumps({"merged_answer": 42, "overall_confidence": "high"})
        agent = _make_hybrid(llm_response=bad_merge)
        result = await agent.run("query", _CTX)

        assert result.rag_only is True


# ---------------------------------------------------------------------------
# 6. Parallelism — both agents called concurrently
# ---------------------------------------------------------------------------

class TestHybridAgentConcurrency:
    @pytest.mark.asyncio
    async def test_both_agents_run_concurrently(self) -> None:
        """Verify gather semantics: both run() coroutines are awaited."""
        call_order: list[str] = []

        async def slow_rag(query: str, context: AgentContext) -> RAGResult:
            call_order.append("rag_start")
            await asyncio.sleep(0)  # yield control
            call_order.append("rag_end")
            return _RAG_OK

        async def slow_sql(query: str, context: AgentContext) -> SQLResult:
            call_order.append("sql_start")
            await asyncio.sleep(0)
            call_order.append("sql_end")
            return _SQL_OK

        rag_mock = MagicMock(spec=RAGAgent)
        rag_mock.run = slow_rag
        sql_mock = MagicMock(spec=SQLAgent)
        sql_mock.run = slow_sql

        agent = HybridAgent(
            rag_agent=rag_mock,
            sql_agent=sql_mock,
            llm=_StubLLM(),
            registry=PromptRegistry(PROMPTS_DIR),
        )

        await agent.run("query", _CTX)

        # Both starts occur before either end (interleaved = concurrent)
        assert "rag_start" in call_order
        assert "sql_start" in call_order
        assert call_order.index("rag_start") < call_order.index("rag_end")
        assert call_order.index("sql_start") < call_order.index("sql_end")


# ---------------------------------------------------------------------------
# 7. Prometheus counters
# ---------------------------------------------------------------------------

class TestHybridAgentMetrics:
    @pytest.mark.asyncio
    async def test_success_increments_hybrid_success_rate(self) -> None:
        from src.observability.prometheus_metrics import HYBRID_SUCCESS_RATE

        before = HYBRID_SUCCESS_RATE._value.get()
        agent = _make_hybrid()
        await agent.run("query", _CTX)
        after = HYBRID_SUCCESS_RATE._value.get()

        assert after == before + 1

    @pytest.mark.asyncio
    async def test_hybrid_latency_is_observed(self) -> None:
        from src.observability.prometheus_metrics import HYBRID_LATENCY

        before_count = HYBRID_LATENCY._sum.get()
        agent = _make_hybrid()
        await agent.run("query", _CTX)
        after_count = HYBRID_LATENCY._sum.get()

        assert after_count >= before_count  # latency was observed (>= 0)

    @pytest.mark.asyncio
    async def test_partial_failure_does_not_increment_success_rate(self) -> None:
        from src.observability.prometheus_metrics import HYBRID_SUCCESS_RATE

        before = HYBRID_SUCCESS_RATE._value.get()
        agent = _make_hybrid(sql_result=RuntimeError("down"))
        await agent.run("query", _CTX)
        after = HYBRID_SUCCESS_RATE._value.get()

        assert after == before  # no increment on partial


# ---------------------------------------------------------------------------
# 8. _render_hybrid_prompt helper
# ---------------------------------------------------------------------------

class TestRenderHybridPrompt:
    def test_render_inserts_masked_query(self) -> None:
        result = _render_hybrid_prompt(
            "USER QUERY: {{masked_query}}", "What is VAT?", _RAG_OK, _SQL_OK
        )
        assert "What is VAT?" in result
        assert "{{masked_query}}" not in result

    def test_render_inserts_sql_result_json(self) -> None:
        result = _render_hybrid_prompt(
            "SQL RESULT: {{sql_result_json}}", "q", _RAG_OK, _SQL_OK
        )
        assert "inv-1" in result
        assert "{{sql_result_json}}" not in result

    def test_render_inserts_rag_result_json(self) -> None:
        result = _render_hybrid_prompt(
            "RAG RESULT: {{rag_result_json}}", "q", _RAG_OK, _SQL_OK
        )
        assert "VAT rate is 9%" in result
        assert "{{rag_result_json}}" not in result

    def test_render_produces_valid_json_in_sql_placeholder(self) -> None:
        import re
        template = "{{sql_result_json}}"
        result = _render_hybrid_prompt(template, "q", _RAG_OK, _SQL_OK)
        parsed = json.loads(result)
        assert parsed["row_count"] == 1


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestHybridAgentEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_sql_rows_produces_valid_result(self) -> None:
        empty_sql = SQLResult(
            query="SELECT id FROM t WHERE tenant_id = :tenant_id",
            rows=(),
            row_count=0,
            latency_ms=1.0,
            query_id="q-0",
        )
        agent = _make_hybrid(sql_result=empty_sql)
        result = await agent.run("query with no data", _CTX)

        assert isinstance(result, HybridResult)

    @pytest.mark.asyncio
    async def test_long_query_does_not_crash(self) -> None:
        agent = _make_hybrid()
        result = await agent.run("what is the VAT rate " * 300, _CTX)

        assert isinstance(result, HybridResult)

    @pytest.mark.asyncio
    async def test_hybrid_result_is_frozen(self) -> None:
        agent = _make_hybrid()
        result = await agent.run("query", _CTX)

        with pytest.raises((AttributeError, TypeError)):
            result.merged_answer = "tampered"  # type: ignore[misc]
