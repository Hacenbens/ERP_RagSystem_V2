"""Unit tests for QueryClassifierPort and StubClassifier — Sprint 7 Task 6."""
from __future__ import annotations

from src.domain.models.routing_decision import RoutingDecision
from src.domain.ports.query_classifier_port import QueryClassifierPort
from src.domain.query_intent import QueryIntent
from src.infrastructure.nlp.stub_classifier import StubClassifier


class TestQueryClassifierPortContract:
    def test_stub_classifier_is_a_query_classifier_port(self) -> None:
        assert isinstance(StubClassifier(), QueryClassifierPort)

    def test_classify_returns_routing_decision(self) -> None:
        result = StubClassifier().classify("What is the VAT rate?")

        assert isinstance(result, RoutingDecision)

    def test_classify_always_returns_hybrid(self) -> None:
        classifier = StubClassifier()

        for query in [
            "What is the VAT rate?",
            "List all invoices for tenant X",
            "How many SKUs are in the warehouse?",
            "",
        ]:
            result = classifier.classify(query)
            assert result.intent == QueryIntent.HYBRID

    def test_classify_returns_full_confidence(self) -> None:
        result = StubClassifier().classify("any query")

        assert result.confidence == 1.0

    def test_classify_erp_module_is_none(self) -> None:
        result = StubClassifier().classify("any query")

        assert result.erp_module is None

    def test_classify_reason_is_non_empty(self) -> None:
        result = StubClassifier().classify("any query")

        assert len(result.reason) > 0

    def test_classify_result_is_immutable(self) -> None:
        result = StubClassifier().classify("any query")

        try:
            result.intent = QueryIntent.RAG  # type: ignore[misc]
            raised = False
        except (AttributeError, TypeError):
            raised = True

        assert raised, "RoutingDecision must be frozen / immutable"

    def test_classify_long_query_does_not_raise(self) -> None:
        long_query = "x " * 500
        result = StubClassifier().classify(long_query)

        assert result.intent == QueryIntent.HYBRID
