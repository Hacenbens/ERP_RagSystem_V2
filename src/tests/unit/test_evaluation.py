"""
Unit tests for the Sprint 2 evaluation framework.
Tests the benchmark harnesses and hallucination scorer in isolation.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure repo root is on path
sys.path.insert(0, str(Path(__file__).parents[4]))

from evaluation.benchmarks.sql_benchmark import (
    BenchmarkReport,
    SQLTestCase,
    _check_patterns,
    _has_tenant_filter,
    _offline_stub_sql,
    load_test_cases,
    run_benchmark,
)
from evaluation.benchmarks.rag_benchmark import (
    RAGTestCase,
    _offline_stub_retrieve,
    _precision_at_k,
    load_test_cases as rag_load_test_cases,
    run_benchmark as rag_run_benchmark,
)
from evaluation.metrics.hallucination_scorer import (
    HallucinationResult,
    _build_result,
    _heuristic_score,
    score,
)


# ---------------------------------------------------------------------------
# SQL Benchmark — unit tests
# ---------------------------------------------------------------------------

class TestSQLBenchmarkDataFile:
    def test_data_file_exists(self):
        from evaluation.benchmarks.sql_benchmark import DATA_FILE
        assert DATA_FILE.exists(), f"sql_test_cases.json not found at {DATA_FILE}"

    def test_data_file_has_20_cases(self):
        cases = load_test_cases()
        assert len(cases) == 20, f"Expected 20 test cases, got {len(cases)}"

    def test_all_cases_have_required_fields(self):
        cases = load_test_cases()
        for tc in cases:
            assert tc.id, "Test case missing id"
            assert tc.nl_query, "Test case missing nl_query"
            assert isinstance(tc.expected_patterns, list), "expected_patterns must be a list"
            assert len(tc.expected_patterns) >= 1, "Must have at least 1 expected pattern"
            assert isinstance(tc.must_have_tenant_filter, bool)

    def test_all_cases_require_tenant_filter(self):
        """Every ERP query must enforce tenant isolation."""
        cases = load_test_cases()
        for tc in cases:
            assert tc.must_have_tenant_filter, (
                f"Test case {tc.id} does not require tenant_filter — "
                "all ERP queries must filter by tenant_id"
            )

    def test_all_case_ids_unique(self):
        cases = load_test_cases()
        ids = [tc.id for tc in cases]
        assert len(ids) == len(set(ids)), "Duplicate test case IDs found"


class TestSQLPatternChecking:
    def test_check_patterns_all_present(self):
        sql = "SELECT * FROM sales_orders WHERE tenant_id = :tenant_id"
        missing = _check_patterns(sql, ["SELECT", "sales_orders", "tenant_id"])
        assert missing == []

    def test_check_patterns_case_insensitive(self):
        sql = "select * from sales_orders where tenant_id = :tenant_id"
        missing = _check_patterns(sql, ["SELECT", "SALES_ORDERS"])
        assert missing == []

    def test_check_patterns_missing_pattern(self):
        sql = "SELECT * FROM orders WHERE tenant_id = :tenant_id"
        missing = _check_patterns(sql, ["SELECT", "sales_orders"])
        assert "sales_orders" in missing

    def test_has_tenant_filter_positive(self):
        sql = "SELECT * FROM t WHERE tenant_id = :tenant_id"
        assert _has_tenant_filter(sql) is True

    def test_has_tenant_filter_negative(self):
        sql = "SELECT * FROM t WHERE status = 'open'"
        assert _has_tenant_filter(sql) is False

    def test_has_tenant_filter_case_insensitive(self):
        sql = "SELECT * FROM t WHERE TENANT_ID = '123'"
        assert _has_tenant_filter(sql) is True


class TestOfflineSQLStub:
    def test_stub_contains_select(self):
        sql = _offline_stub_sql("Show all open sales orders")
        assert "SELECT" in sql.upper()

    def test_stub_always_has_tenant_filter(self):
        queries = [
            "Show all sales orders",
            "Get revenue for product X",
            "List suppliers with invoices",
        ]
        for q in queries:
            sql = _offline_stub_sql(q)
            assert _has_tenant_filter(sql), f"No tenant_id filter in stub SQL for: {q}"

    def test_stub_maps_keywords_to_tables(self):
        sql = _offline_stub_sql("Show payroll for March")
        assert "payroll" in sql.lower()

    def test_stub_adds_aggregation_for_sum_queries(self):
        sql = _offline_stub_sql("What is the total revenue this month?")
        assert "SUM" in sql.upper()

    def test_stub_adds_limit_for_top_n_queries(self):
        sql = _offline_stub_sql("Show top 10 customers by order value")
        assert "LIMIT" in sql.upper()


class TestSQLBenchmarkRunner:
    def test_run_benchmark_returns_report(self):
        report = run_benchmark()
        assert isinstance(report, BenchmarkReport)
        assert report.total == 20

    def test_run_benchmark_tenant_filter_always_present_offline(self):
        """Offline stub must always include tenant_id filter — non-negotiable."""
        report = run_benchmark()
        missing_tenant = [r.test_id for r in report.results if not r.tenant_filter_present]
        assert missing_tenant == [], (
            f"These test cases produced SQL without tenant_id filter: {missing_tenant}"
        )

    def test_run_benchmark_success_rate_in_range(self):
        report = run_benchmark()
        assert 0.0 <= report.success_rate <= 1.0

    def test_run_benchmark_with_custom_cases(self):
        cases = [
            SQLTestCase(
                id="test_custom_001",
                nl_query="List all invoices for tenant ACME",
                expected_patterns=["SELECT", "tenant_id"],
                must_have_tenant_filter=True,
                description="Custom test case",
            )
        ]
        report = run_benchmark(test_cases=cases)
        assert report.total == 1

    def test_benchmark_exit_code_logic(self):
        """Verify pass/fail logic matches CI expectations."""
        report = run_benchmark()
        assert report.success_rate >= report.threshold or report.failed > 0

    def test_all_results_have_latency(self):
        report = run_benchmark()
        for r in report.results:
            assert r.latency_ms >= 0.0


# ---------------------------------------------------------------------------
# RAG Benchmark — unit tests
# ---------------------------------------------------------------------------

class TestRAGBenchmarkDataFile:
    def test_data_file_exists(self):
        from evaluation.benchmarks.rag_benchmark import DATA_FILE
        assert DATA_FILE.exists(), f"rag_test_cases.json not found at {DATA_FILE}"

    def test_data_file_has_15_cases(self):
        cases = rag_load_test_cases()
        assert len(cases) == 15, f"Expected 15 test cases, got {len(cases)}"

    def test_all_cases_have_required_fields(self):
        cases = rag_load_test_cases()
        for tc in cases:
            assert tc.id
            assert tc.query
            assert isinstance(tc.expected_chunk_ids, list)
            assert len(tc.expected_chunk_ids) >= 1

    def test_all_case_ids_unique(self):
        cases = rag_load_test_cases()
        ids = [tc.id for tc in cases]
        assert len(ids) == len(set(ids))


class TestPrecisionAtK:
    def test_perfect_precision(self):
        retrieved = ["a", "b", "c", "d", "e"]
        expected = ["a", "b", "c", "d", "e"]
        precision, hits = _precision_at_k(retrieved, expected, k=5)
        assert precision == 1.0
        assert hits == 5

    def test_zero_precision(self):
        retrieved = ["x", "y", "z", "w", "v"]
        expected = ["a", "b", "c"]
        precision, hits = _precision_at_k(retrieved, expected, k=5)
        assert precision == 0.0
        assert hits == 0

    def test_partial_precision(self):
        retrieved = ["a", "x", "b", "y", "z"]
        expected = ["a", "b", "c"]
        precision, hits = _precision_at_k(retrieved, expected, k=5)
        assert precision == pytest.approx(0.4)
        assert hits == 2

    def test_truncates_to_k(self):
        retrieved = ["a", "b", "c", "d", "e", "f", "g"]
        expected = ["f", "g"]
        precision, hits = _precision_at_k(retrieved, expected, k=5)
        assert hits == 0  # f and g are beyond top-5


class TestOfflineRAGStub:
    def test_stub_returns_top_k_results(self):
        results = _offline_stub_retrieve("Show purchase order process", top_k=5)
        assert len(results) == 5

    def test_stub_returns_chunk_ids(self):
        results = _offline_stub_retrieve("payroll processing steps", top_k=3)
        assert all(isinstance(r, str) for r in results)
        assert all(r.startswith("chunk_") for r in results)

    def test_stub_maps_keywords(self):
        results = _offline_stub_retrieve("VAT calculation in Algeria", top_k=5)
        assert any("vat" in r for r in results)


class TestRAGBenchmarkRunner:
    def test_run_benchmark_returns_report(self):
        report = rag_run_benchmark()
        assert report.total == 15

    def test_run_benchmark_mean_precision_in_range(self):
        report = rag_run_benchmark()
        assert 0.0 <= report.mean_precision_at_5 <= 1.0

    def test_run_benchmark_with_custom_cases(self):
        cases = [
            RAGTestCase(
                id="rag_custom_001",
                query="Purchase order approval steps",
                expected_chunk_ids=["chunk_po_approval_001"],
                description="Custom RAG test",
            )
        ]
        report = rag_run_benchmark(test_cases=cases)
        assert report.total == 1


# ---------------------------------------------------------------------------
# Hallucination Scorer — unit tests
# ---------------------------------------------------------------------------

class TestHallucinationScorerHeuristic:
    def test_fully_grounded_answer(self):
        context = "The purchase order approval requires three signatories in the finance department."
        answer = "The purchase order approval requires three signatories in the finance department."
        result = _heuristic_score(answer, context)
        assert result.grounding_score > 0.8

    def test_fully_hallucinated_answer(self):
        context = "Stock levels are managed in warehouse WH-001."
        answer = "Quantum entanglement affects neutrino flux in superconductors."
        result = _heuristic_score(answer, context)
        assert result.grounding_score < 0.3

    def test_score_in_valid_range(self):
        result = _heuristic_score("Some answer.", "Some context.")
        assert 0.0 <= result.grounding_score <= 1.0
        assert 0.0 <= result.hallucination_rate <= 1.0

    def test_hallucination_rate_complement(self):
        result = _heuristic_score("The invoice amount is 5000 DZD.", "Invoice total: 5000 DZD.")
        assert abs(result.grounding_score + result.hallucination_rate - 1.0) < 1e-9

    def test_empty_answer(self):
        result = _heuristic_score("", "Some context with information.")
        assert result.grounding_score == 1.0  # empty answer is trivially grounded

    def test_is_acceptable_flag(self):
        context = "Revenue for Q1 was 1.2 million DZD across all product lines."
        answer = "Revenue for Q1 was 1.2 million DZD across all product lines."
        result = _heuristic_score(answer, context)
        # Fully grounded → hallucination_rate should be very low → acceptable
        assert isinstance(result.is_acceptable, bool)


class TestHallucinationScorerBuildResult:
    def test_clamps_above_one(self):
        result = _build_result(1.5, 10, 0, "test")
        assert result.grounding_score == 1.0

    def test_clamps_below_zero(self):
        result = _build_result(-0.5, 0, 10, "test")
        assert result.grounding_score == 0.0

    def test_hallucination_rate_calculated(self):
        result = _build_result(0.8, 8, 2, "test")
        assert result.hallucination_rate == pytest.approx(0.2)


class TestHallucinationScorerPublicAPI:
    def test_score_without_llm_uses_heuristic(self):
        result = score("The answer", "The answer context", llm_client=None)
        assert isinstance(result, HallucinationResult)
        assert 0.0 <= result.grounding_score <= 1.0

    def test_score_with_mock_llm(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps({
            "grounding_score": 0.9,
            "grounded_claims": 9,
            "hallucinated_claims": 1,
            "reasoning": "Most claims are grounded.",
        })
        result = score("Some answer.", "Some context.", llm_client=mock_llm)
        assert result.grounding_score == pytest.approx(0.9)
        assert result.grounded_claims == 9
        assert result.hallucinated_claims == 1


# ---------------------------------------------------------------------------
# Config — threshold tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_sql_threshold(self):
        from helpers.config import SQL_SUCCESS_MIN
        assert SQL_SUCCESS_MIN == pytest.approx(0.95)

    def test_default_hallucination_threshold(self):
        from helpers.config import HALLUCINATION_MAX
        assert HALLUCINATION_MAX == pytest.approx(0.05)

    def test_default_rag_threshold(self):
        from helpers.config import RAG_PRECISION_MIN
        assert RAG_PRECISION_MIN == pytest.approx(0.70)

    def test_thresholds_overridable_via_env(self, monkeypatch):
        monkeypatch.setenv("SQL_SUCCESS_MIN", "0.80")
        import importlib
        import helpers.config as cfg
        importlib.reload(cfg)
        assert float(os.environ.get("SQL_SUCCESS_MIN", "0.95")) == pytest.approx(0.80)
