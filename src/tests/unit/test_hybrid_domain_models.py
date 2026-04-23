"""
Unit tests for Sprint 7 domain models.

Covers: ScoredChunk, RoutingDecision, RAGResult, SQLResult, HybridResult
"""
from __future__ import annotations

import pytest

from src.domain.erp_module import ErpModule
from src.domain.models import (
    HybridResult,
    RAGResult,
    RoutingDecision,
    SQLResult,
    ScoredChunk,
)
from src.domain.query_intent import QueryIntent


# ---------------------------------------------------------------------------
# ScoredChunk
# ---------------------------------------------------------------------------

class TestScoredChunk:
    def test_basic_construction(self) -> None:
        chunk = ScoredChunk(
            chunk_id="c-001",
            content="VAT rate for pharmaceuticals is 9%.",
            score=0.92,
            source="tax_circular_2024.pdf",
            erp_module="finance",
        )
        assert chunk.chunk_id == "c-001"
        assert chunk.score == 0.92
        assert chunk.erp_module == "finance"

    def test_erp_module_optional(self) -> None:
        chunk = ScoredChunk(chunk_id="c-002", content="text", score=0.5, source="doc.pdf")
        assert chunk.erp_module is None

    def test_is_frozen(self) -> None:
        chunk = ScoredChunk(chunk_id="c-003", content="text", score=0.7, source="doc.pdf")
        with pytest.raises((AttributeError, TypeError)):
            chunk.score = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RoutingDecision
# ---------------------------------------------------------------------------

class TestRoutingDecision:
    def test_hybrid_intent(self) -> None:
        dec = RoutingDecision(
            intent=QueryIntent.HYBRID,
            confidence=0.91,
            erp_module=ErpModule.FINANCE,
            reason="Query needs both data and policy context.",
        )
        assert dec.intent == QueryIntent.HYBRID
        assert dec.confidence == 0.91
        assert dec.erp_module == ErpModule.FINANCE

    def test_blocked_intent(self) -> None:
        dec = RoutingDecision(
            intent=QueryIntent.BLOCKED,
            confidence=0.99,
            erp_module=None,
            reason="SQL injection attempt detected.",
        )
        assert dec.intent == QueryIntent.BLOCKED
        assert dec.erp_module is None

    def test_is_frozen(self) -> None:
        dec = RoutingDecision(
            intent=QueryIntent.RAG,
            confidence=0.85,
            erp_module=None,
            reason="Policy question.",
        )
        with pytest.raises((AttributeError, TypeError)):
            dec.confidence = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RAGResult
# ---------------------------------------------------------------------------

class TestRAGResult:
    def test_grounded_result(self) -> None:
        result = RAGResult(
            grounded=True,
            answer="The VAT rate is 9% [c-001].",
            cited_chunks=("c-001", "c-002"),
            grounding_score=0.88,
            confidence=0.91,
            insufficient_data_for=(),
        )
        assert result.grounded is True
        assert "c-001" in result.cited_chunks
        assert result.grounding_score == 0.88

    def test_not_grounded_constructor(self) -> None:
        result = RAGResult.not_grounded()
        assert result.grounded is False
        assert result.answer is None
        assert result.cited_chunks == ()
        assert result.grounding_score == 0.0
        assert result.confidence == 0.0

    def test_partial_grounding(self) -> None:
        result = RAGResult(
            grounded=True,
            answer="Partial answer.",
            cited_chunks=("c-003",),
            grounding_score=0.6,
            confidence=0.7,
            insufficient_data_for=("exact penalty amount",),
        )
        assert "exact penalty amount" in result.insufficient_data_for

    def test_is_frozen(self) -> None:
        result = RAGResult.not_grounded()
        with pytest.raises((AttributeError, TypeError)):
            result.grounded = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SQLResult
# ---------------------------------------------------------------------------

class TestSQLResult:
    def test_basic_construction(self) -> None:
        result = SQLResult(
            query="SELECT * FROM invoices WHERE tenant_id = $1",
            rows=({"invoice_id": "INV-001", "amount": 5000.0},),
            row_count=1,
            latency_ms=42.5,
            tables_used=("invoices",),
            query_id="q-abc-123",
        )
        assert result.row_count == 1
        assert result.latency_ms == 42.5
        assert result.success is True

    def test_empty_rows(self) -> None:
        result = SQLResult(
            query="SELECT * FROM invoices WHERE tenant_id = $1 AND id = 'x'",
            rows=(),
            row_count=0,
            latency_ms=10.0,
        )
        assert result.row_count == 0
        assert result.rows == ()
        assert result.tables_used == ()

    def test_is_frozen(self) -> None:
        result = SQLResult(
            query="SELECT 1",
            rows=(),
            row_count=0,
            latency_ms=5.0,
        )
        with pytest.raises((AttributeError, TypeError)):
            result.row_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HybridResult
# ---------------------------------------------------------------------------

class TestHybridResult:
    def _make_rag(self) -> RAGResult:
        return RAGResult(
            grounded=True,
            answer="Policy says 9%.",
            cited_chunks=("c-001",),
            grounding_score=0.9,
            confidence=0.88,
        )

    def _make_sql(self) -> SQLResult:
        return SQLResult(
            query="SELECT count(*) FROM vat_transactions WHERE tenant_id = $1",
            rows=({"count": 42},),
            row_count=1,
            latency_ms=55.0,
            tables_used=("vat_transactions",),
        )

    def test_full_hybrid(self) -> None:
        result = HybridResult(
            rag_result=self._make_rag(),
            sql_result=self._make_sql(),
            merged_answer="The VAT rate is 9% and we recorded 42 transactions.",
            sql_contribution="42 VAT transactions in Q1.",
            rag_contribution="VAT rate 9% from tax circular.",
            overall_confidence=0.89,
            cited_chunks=("c-001",),
            sql_tables_used=("vat_transactions",),
        )
        assert result.merged_answer is not None
        assert result.is_partial is False
        assert result.rag_only is False
        assert result.sql_only is False

    def test_rag_fallback_constructor(self) -> None:
        rag = self._make_rag()
        result = HybridResult.rag_fallback(rag)
        assert result.rag_only is True
        assert result.sql_result is None
        assert result.merged_answer is None
        assert result.is_partial is True

    def test_sql_fallback_constructor(self) -> None:
        sql = self._make_sql()
        result = HybridResult.sql_fallback(sql)
        assert result.sql_only is True
        assert result.rag_result is None
        assert result.merged_answer is None
        assert result.is_partial is True

    def test_is_frozen(self) -> None:
        result = HybridResult.rag_fallback(self._make_rag())
        with pytest.raises((AttributeError, TypeError)):
            result.rag_only = False  # type: ignore[misc]
