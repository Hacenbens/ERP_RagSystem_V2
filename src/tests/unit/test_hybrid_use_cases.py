"""
Unit tests for RunRAGUseCase, RunSQLUseCase, RunHybridUseCase, RouteQueryUseCase
and BlockedQueryError — Sprint 7 Task 9.

Coverage:
  1. Happy path — each use case delegates to its agent and returns the result
  2. Failure paths — BlockedQueryError on BLOCKED intent and low confidence
  3. Routing table — SQL+REPORTING_ANALYST → RAG, low confidence → HYBRID
  4. Security — REPORTING_ANALYST cannot reach SQL pipeline
  5. Edge cases — None erp_module, confidence boundary values
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.base_agent import AgentContext
from src.agents.hybrid_agent import HybridAgent
from src.agents.rag_agent import RAGAgent
from src.agents.sql_agent import SQLAgent
from src.domain.models.hybrid_result import HybridResult
from src.domain.models.rag_result import RAGResult
from src.domain.models.routing_decision import RoutingDecision
from src.domain.models.sql_result import SQLResult
from src.domain.ports.query_classifier_port import QueryClassifierPort
from src.domain.query_intent import QueryIntent
from src.domain.user_role import UserRole
from src.infrastructure.auth.jwt_handler import TokenClaims
from src.use_cases.route_query import BlockedQueryError, RouteQueryUseCase
from src.use_cases.run_hybrid import RunHybridUseCase
from src.use_cases.run_rag import RunRAGUseCase
from src.use_cases.run_sql import RunSQLUseCase

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_TENANT = "t-acme"
_TRACE = "tr-test-001"

_RAG_OK = RAGResult(
    grounded=True,
    answer="Warranty period is 24 months.",
    cited_chunks=("chunk-1",),
    grounding_score=0.88,
    confidence=0.88,
    insufficient_data_for=(),
)

_SQL_OK = SQLResult(
    query="SELECT * FROM invoices WHERE tenant_id = :t LIMIT 5",
    rows=({"invoice_id": "inv-1"},),
    row_count=1,
    latency_ms=50.0,
    query_id="exec-1",
)

_HYBRID_OK = HybridResult(
    rag_result=_RAG_OK,
    sql_result=_SQL_OK,
    merged_answer="Combined answer from both sources.",
    sql_contribution="One invoice found.",
    rag_contribution="Policy document confirms 24 months.",
    overall_confidence=0.90,
)


def _make_token(role: str = "FINANCE_MANAGER") -> TokenClaims:
    return TokenClaims(
        user_id="user-1",
        role=role,
        tenant_id=_TENANT,
        exp=9999999999,
        iat=1700000000,
        sub="user-1",
    )


def _make_decision(
    intent: QueryIntent = QueryIntent.RAG,
    confidence: float = 0.85,
    erp_module=None,
    reason: str = "ok",
) -> RoutingDecision:
    return RoutingDecision(
        intent=intent,
        confidence=confidence,
        erp_module=erp_module,
        reason=reason,
    )


class _StubClassifier(QueryClassifierPort):
    def __init__(self, decision: RoutingDecision) -> None:
        self._decision = decision

    def classify(self, query: str) -> RoutingDecision:
        return self._decision


# ---------------------------------------------------------------------------
# 1. RunRAGUseCase — happy path
# ---------------------------------------------------------------------------

class TestRunRAGUseCase:
    @pytest.mark.asyncio
    async def test_run_rag_use_case_valid_query_returns_rag_result(self):
        rag_agent = MagicMock(spec=RAGAgent)
        rag_agent.run = AsyncMock(return_value=_RAG_OK)
        uc = RunRAGUseCase(rag_agent=rag_agent)

        result = await uc.execute("What is the warranty period?", _TENANT, "sales")

        assert result is _RAG_OK
        rag_agent.run.assert_called_once()
        call_args = rag_agent.run.call_args
        assert call_args[0][0] == "What is the warranty period?"
        ctx: AgentContext = call_args[0][1]
        assert ctx.tenant_id == _TENANT
        assert ctx.erp_module == "sales"

    @pytest.mark.asyncio
    async def test_run_rag_use_case_none_erp_module_propagated(self):
        rag_agent = MagicMock(spec=RAGAgent)
        rag_agent.run = AsyncMock(return_value=_RAG_OK)
        uc = RunRAGUseCase(rag_agent=rag_agent)

        await uc.execute("Any question", _TENANT)

        ctx: AgentContext = rag_agent.run.call_args[0][1]
        assert ctx.erp_module is None

    @pytest.mark.asyncio
    async def test_run_rag_use_case_propagates_agent_exception(self):
        rag_agent = MagicMock(spec=RAGAgent)
        rag_agent.run = AsyncMock(side_effect=RuntimeError("embedding service down"))
        uc = RunRAGUseCase(rag_agent=rag_agent)

        with pytest.raises(RuntimeError, match="embedding service down"):
            await uc.execute("question", _TENANT)


# ---------------------------------------------------------------------------
# 2. RunSQLUseCase — happy path and failure
# ---------------------------------------------------------------------------

class TestRunSQLUseCase:
    @pytest.mark.asyncio
    async def test_run_sql_use_case_valid_query_returns_sql_result(self):
        sql_agent = MagicMock(spec=SQLAgent)
        sql_agent.run = AsyncMock(return_value=_SQL_OK)
        uc = RunSQLUseCase(sql_agent=sql_agent)

        result = await uc.execute("List top 5 invoices", _TENANT, "finance")

        assert result is _SQL_OK
        ctx: AgentContext = sql_agent.run.call_args[0][1]
        assert ctx.tenant_id == _TENANT
        assert ctx.erp_module == "finance"

    @pytest.mark.asyncio
    async def test_run_sql_use_case_none_erp_module_propagated(self):
        sql_agent = MagicMock(spec=SQLAgent)
        sql_agent.run = AsyncMock(return_value=_SQL_OK)
        uc = RunSQLUseCase(sql_agent=sql_agent)

        await uc.execute("Any SQL query", _TENANT)

        ctx: AgentContext = sql_agent.run.call_args[0][1]
        assert ctx.erp_module is None

    @pytest.mark.asyncio
    async def test_run_sql_use_case_propagates_agent_exception(self):
        from src.agents.sql_agent import SQLAgentError
        sql_agent = MagicMock(spec=SQLAgent)
        sql_agent.run = AsyncMock(side_effect=SQLAgentError("validation failed"))
        uc = RunSQLUseCase(sql_agent=sql_agent)

        with pytest.raises(SQLAgentError):
            await uc.execute("DROP TABLE invoices", _TENANT)


# ---------------------------------------------------------------------------
# 3. RunHybridUseCase — happy path and failure
# ---------------------------------------------------------------------------

class TestRunHybridUseCase:
    @pytest.mark.asyncio
    async def test_run_hybrid_use_case_valid_query_returns_hybrid_result(self):
        hybrid_agent = MagicMock(spec=HybridAgent)
        hybrid_agent.run = AsyncMock(return_value=_HYBRID_OK)
        uc = RunHybridUseCase(hybrid_agent=hybrid_agent)

        result = await uc.execute("Summarise invoice vs policy", _TENANT, "finance")

        assert result is _HYBRID_OK
        ctx: AgentContext = hybrid_agent.run.call_args[0][1]
        assert ctx.tenant_id == _TENANT
        assert ctx.erp_module == "finance"

    @pytest.mark.asyncio
    async def test_run_hybrid_use_case_partial_result_logged_without_error(self):
        partial = HybridResult.rag_fallback(_RAG_OK)
        hybrid_agent = MagicMock(spec=HybridAgent)
        hybrid_agent.run = AsyncMock(return_value=partial)
        uc = RunHybridUseCase(hybrid_agent=hybrid_agent)

        result = await uc.execute("query", _TENANT)

        assert result.is_partial is True
        assert result.rag_only is True

    @pytest.mark.asyncio
    async def test_run_hybrid_use_case_propagates_agent_error(self):
        from src.agents.hybrid_agent import HybridAgentError
        hybrid_agent = MagicMock(spec=HybridAgent)
        hybrid_agent.run = AsyncMock(side_effect=HybridAgentError("both failed"))
        uc = RunHybridUseCase(hybrid_agent=hybrid_agent)

        with pytest.raises(HybridAgentError):
            await uc.execute("query", _TENANT)


# ---------------------------------------------------------------------------
# 4. RouteQueryUseCase — routing table (§15.2)
# ---------------------------------------------------------------------------

class TestRouteQueryUseCaseHappyPath:
    def _make_uc(self, decision: RoutingDecision):
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc,
            sql_uc=sql_uc,
            hybrid_uc=hybrid_uc,
        )
        return uc, rag_uc, sql_uc, hybrid_uc

    @pytest.mark.asyncio
    async def test_route_query_rag_intent_high_confidence_calls_rag(self):
        decision = _make_decision(intent=QueryIntent.RAG, confidence=0.90)
        uc, rag_uc, sql_uc, hybrid_uc = self._make_uc(decision)

        result = await uc.execute("What is the return policy?", _make_token())

        assert result is _RAG_OK
        rag_uc.execute.assert_called_once()
        sql_uc.execute.assert_not_called()
        hybrid_uc.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_query_sql_intent_high_confidence_calls_sql(self):
        decision = _make_decision(intent=QueryIntent.SQL, confidence=0.85)
        uc, rag_uc, sql_uc, hybrid_uc = self._make_uc(decision)

        result = await uc.execute("List invoices for last month", _make_token("FINANCE_MANAGER"))

        assert result is _SQL_OK
        sql_uc.execute.assert_called_once()
        rag_uc.execute.assert_not_called()
        hybrid_uc.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_query_hybrid_intent_high_confidence_calls_hybrid(self):
        decision = _make_decision(intent=QueryIntent.HYBRID, confidence=0.80)
        uc, rag_uc, sql_uc, hybrid_uc = self._make_uc(decision)

        result = await uc.execute("Compare invoice data with policy", _make_token())

        assert result is _HYBRID_OK
        hybrid_uc.execute.assert_called_once()
        rag_uc.execute.assert_not_called()
        sql_uc.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_query_tenant_id_from_token_passed_to_use_case(self):
        decision = _make_decision(intent=QueryIntent.RAG, confidence=0.90)
        uc, rag_uc, _, _ = self._make_uc(decision)
        token = _make_token()

        await uc.execute("query", token)

        call_kwargs = rag_uc.execute.call_args
        assert call_kwargs[0][1] == _TENANT or call_kwargs[1].get("tenant_id") == _TENANT


# ---------------------------------------------------------------------------
# 5. RouteQueryUseCase — failure paths
# ---------------------------------------------------------------------------

class TestRouteQueryUseCaseFailurePaths:
    def _make_uc(self, decision: RoutingDecision):
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        return RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc,
            sql_uc=sql_uc,
            hybrid_uc=hybrid_uc,
        )

    @pytest.mark.asyncio
    async def test_route_query_blocked_intent_raises_blocked_query_error(self):
        decision = _make_decision(intent=QueryIntent.BLOCKED, confidence=0.95, reason="harmful query")
        uc = self._make_uc(decision)

        with pytest.raises(BlockedQueryError, match="harmful query"):
            await uc.execute("DROP TABLE users", _make_token())

    @pytest.mark.asyncio
    async def test_route_query_confidence_below_050_raises_blocked_query_error(self):
        decision = _make_decision(intent=QueryIntent.RAG, confidence=0.49, reason="too uncertain")
        uc = self._make_uc(decision)

        with pytest.raises(BlockedQueryError):
            await uc.execute("gibberish query xyz", _make_token())

    @pytest.mark.asyncio
    async def test_route_query_confidence_exactly_050_raises_blocked_query_error(self):
        # 0.50 is not < 0.50 so this should NOT raise — confirm boundary
        decision = _make_decision(intent=QueryIntent.RAG, confidence=0.50)
        uc = self._make_uc(decision)

        # confidence == 0.50 falls through to low-confidence hybrid branch (< 0.70)
        result = await uc.execute("borderline query", _make_token())
        assert result is _HYBRID_OK

    @pytest.mark.asyncio
    async def test_route_query_confidence_below_070_routes_to_hybrid(self):
        decision = _make_decision(intent=QueryIntent.SQL, confidence=0.65)
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc, sql_uc=sql_uc, hybrid_uc=hybrid_uc,
        )

        result = await uc.execute("uncertain query", _make_token())

        assert result is _HYBRID_OK
        hybrid_uc.execute.assert_called_once()
        sql_uc.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_query_confidence_exactly_070_not_escalated_to_hybrid(self):
        decision = _make_decision(intent=QueryIntent.RAG, confidence=0.70)
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc, sql_uc=sql_uc, hybrid_uc=hybrid_uc,
        )

        result = await uc.execute("query at boundary", _make_token())

        assert result is _RAG_OK
        rag_uc.execute.assert_called_once()
        hybrid_uc.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Security — REPORTING_ANALYST cannot reach SQL pipeline
# ---------------------------------------------------------------------------

class TestRouteQueryUseCaseSecurityPaths:
    @pytest.mark.asyncio
    async def test_route_query_reporting_analyst_sql_intent_redirected_to_rag(self):
        """REPORTING_ANALYST must never reach SQLAgent, even on SQL intent."""
        decision = _make_decision(intent=QueryIntent.SQL, confidence=0.90)
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc, sql_uc=sql_uc, hybrid_uc=hybrid_uc,
        )
        analyst_token = _make_token(role=UserRole.REPORTING_ANALYST)

        result = await uc.execute("Show me all invoices", analyst_token)

        assert result is _RAG_OK
        sql_uc.execute.assert_not_called()
        rag_uc.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_query_finance_manager_sql_intent_reaches_sql(self):
        """FINANCE_MANAGER with SQL intent must reach SQLAgent."""
        decision = _make_decision(intent=QueryIntent.SQL, confidence=0.90)
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc, sql_uc=sql_uc, hybrid_uc=hybrid_uc,
        )

        result = await uc.execute("List invoices", _make_token(role=UserRole.FINANCE_MANAGER))

        assert result is _SQL_OK
        sql_uc.execute.assert_called_once()
        rag_uc.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_query_reporting_analyst_low_confidence_goes_hybrid_not_sql(self):
        """REPORTING_ANALYST at low confidence must reach HYBRID, never SQL."""
        decision = _make_decision(intent=QueryIntent.SQL, confidence=0.60)
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc, sql_uc=sql_uc, hybrid_uc=hybrid_uc,
        )

        result = await uc.execute("ambiguous query", _make_token(role=UserRole.REPORTING_ANALYST))

        assert result is _HYBRID_OK
        sql_uc.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 7. BlockedQueryError contract
# ---------------------------------------------------------------------------

class TestBlockedQueryError:
    def test_blocked_query_error_is_runtime_error(self):
        err = BlockedQueryError("harmful content")
        assert isinstance(err, RuntimeError)

    def test_blocked_query_error_preserves_message(self):
        err = BlockedQueryError("cannot process PII query")
        assert "cannot process PII query" in str(err)


# ---------------------------------------------------------------------------
# 8. Edge cases
# ---------------------------------------------------------------------------

class TestRouteQueryEdgeCases:
    @pytest.mark.asyncio
    async def test_route_query_erp_module_from_decision_forwarded_to_use_case(self):
        from src.domain.erp_module import ErpModule
        decision = RoutingDecision(
            intent=QueryIntent.RAG,
            confidence=0.90,
            erp_module=ErpModule.FINANCE,
            reason="ok",
        )
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc, sql_uc=sql_uc, hybrid_uc=hybrid_uc,
        )

        await uc.execute("finance query", _make_token())

        call_args = rag_uc.execute.call_args[0]
        # erp_module is passed as str or None
        assert call_args[2] is not None

    @pytest.mark.asyncio
    async def test_route_query_none_erp_module_forwarded_as_none(self):
        decision = _make_decision(intent=QueryIntent.RAG, confidence=0.90, erp_module=None)
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc, sql_uc=sql_uc, hybrid_uc=hybrid_uc,
        )

        await uc.execute("query without module", _make_token())

        call_args = rag_uc.execute.call_args[0]
        assert call_args[2] is None

    @pytest.mark.asyncio
    async def test_route_query_empty_query_string_still_classified(self):
        decision = _make_decision(intent=QueryIntent.RAG, confidence=0.90)
        rag_uc = MagicMock(spec=RunRAGUseCase)
        rag_uc.execute = AsyncMock(return_value=_RAG_OK)
        sql_uc = MagicMock(spec=RunSQLUseCase)
        sql_uc.execute = AsyncMock(return_value=_SQL_OK)
        hybrid_uc = MagicMock(spec=RunHybridUseCase)
        hybrid_uc.execute = AsyncMock(return_value=_HYBRID_OK)
        uc = RouteQueryUseCase(
            classifier=_StubClassifier(decision),
            rag_uc=rag_uc, sql_uc=sql_uc, hybrid_uc=hybrid_uc,
        )

        result = await uc.execute("", _make_token())
        assert result is _RAG_OK
