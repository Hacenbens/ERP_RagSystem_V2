"""QueryClassifierPort — abstract interface for query intent classification."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.models.routing_decision import RoutingDecision


class QueryClassifierPort(ABC):
    """Classify a natural-language query into a routing intent.

    Implementations live in ``src/infrastructure/nlp/``.
    Sprint 7 ships a ``StubClassifier`` that always returns HYBRID.
    The full LLM-backed classifier is Sprint 9.
    """

    @abstractmethod
    def classify(self, query: str) -> RoutingDecision:
        """Return a RoutingDecision for the given *query* string."""
        ...


__all__ = ["QueryClassifierPort"]
