"""RouteQueryUseCase — classify incoming query and dispatch to correct agent.

Routing table (§15.2):
  BLOCKED intent or confidence < 0.50  → BlockedQueryError
  confidence < 0.70 (any intent)       → HYBRID  (safe fallback)
  SQL intent + REPORTING_ANALYST role  → RAG     (no SQL for analysts)
  SQL intent (other roles)             → SQL
  RAG intent                           → RAG
  HYBRID intent (or fallthrough)       → HYBRID
"""
from __future__ import annotations

from typing import Union

from src.domain.models.hybrid_result import HybridResult
from src.domain.models.rag_result import RAGResult
from src.domain.models.sql_result import SQLResult
from src.domain.ports.query_classifier_port import QueryClassifierPort
from src.domain.query_intent import QueryIntent
from src.domain.user_role import UserRole
from src.infrastructure.auth.jwt_handler import TokenClaims
from src.observability.stage_timer import Stage, stage_timer
from src.observability.structured_logger import get_logger
from src.use_cases.run_hybrid import RunHybridUseCase
from src.use_cases.run_rag import RunRAGUseCase
from src.use_cases.run_sql import RunSQLUseCase

logger = get_logger(__name__)

RouteResult = Union[RAGResult, SQLResult, HybridResult]


class BlockedQueryError(RuntimeError):
    """Raised when the classifier rejects a query as BLOCKED or low-confidence."""


class RouteQueryUseCase:
    """Classify a query and route it to RAG, SQL, or Hybrid pipeline.

    Args:
        classifier: port that returns a RoutingDecision for any NL query.
        rag_uc:     executes the RAG pipeline.
        sql_uc:     executes the SQL pipeline.
        hybrid_uc:  executes RAG + SQL in parallel.
    """

    def __init__(
        self,
        classifier: QueryClassifierPort,
        rag_uc: RunRAGUseCase,
        sql_uc: RunSQLUseCase,
        hybrid_uc: RunHybridUseCase,
    ) -> None:
        self._classifier = classifier
        self._rag = rag_uc
        self._sql = sql_uc
        self._hybrid = hybrid_uc

    async def execute(
        self,
        query: str,
        user: TokenClaims,
    ) -> RouteResult:
        """Route query to the appropriate agent and return its result."""
        with stage_timer(Stage.CLASSIFY) as timing:
            decision = self._classifier.classify(query)

        logger.info(
            "route_query.classified",
            intent=decision.intent,
            confidence=decision.confidence,
            latency_ms=round(timing.elapsed_ms, 2),
            erp_module=str(decision.erp_module) if decision.erp_module else None,
            role=user.role,
            tenant_id=user.tenant_id,
        )

        if decision.intent == QueryIntent.BLOCKED or decision.confidence < 0.50:
            logger.warning(
                "route_query.blocked",
                reason=decision.reason,
                confidence=decision.confidence,
            )
            raise BlockedQueryError(decision.reason)

        erp_module = str(decision.erp_module) if decision.erp_module else None

        if decision.confidence < 0.70:
            logger.info("route_query.low_confidence_hybrid", confidence=decision.confidence)
            return await self._hybrid.execute(query, user.tenant_id, erp_module)

        if decision.intent == QueryIntent.SQL and user.role == UserRole.REPORTING_ANALYST:
            logger.info("route_query.reporting_analyst_rag_override")
            return await self._rag.execute(query, user.tenant_id, erp_module)

        if decision.intent == QueryIntent.SQL:
            return await self._sql.execute(query, user.tenant_id, erp_module)

        if decision.intent == QueryIntent.RAG:
            return await self._rag.execute(query, user.tenant_id, erp_module)

        return await self._hybrid.execute(query, user.tenant_id, erp_module)


__all__ = ["BlockedQueryError", "RouteQueryUseCase", "RouteResult"]
