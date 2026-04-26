"""StubClassifier — always returns HYBRID; used only in Sprint 7 tests.

The full LLM-backed classifier (Sprint 9) replaces this in the production
DI container.  This stub is wired only in test fixtures and never registered
in the production factory.
"""
from __future__ import annotations

from src.domain.models.routing_decision import RoutingDecision
from src.domain.ports.query_classifier_port import QueryClassifierPort
from src.domain.query_intent import QueryIntent
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class StubClassifier(QueryClassifierPort):
    """Safe-fallback classifier that routes every query to HYBRID.

    Rationale: HYBRID executes both RAG and SQL branches, so it can never
    under-serve a query — it may over-fetch, but it will never miss data.
    """

    def classify(self, query: str) -> RoutingDecision:
        """Return HYBRID with confidence=1.0 for any *query*."""
        logger.info("stub_classifier.classify", query_preview=query[:80], intent="HYBRID")
        return RoutingDecision(
            intent=QueryIntent.HYBRID,
            confidence=1.0,
            erp_module=None,
            reason="StubClassifier: always HYBRID (Sprint 7 placeholder)",
        )


__all__ = ["StubClassifier"]
