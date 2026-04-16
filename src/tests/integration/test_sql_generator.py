"""
Integration tests — Stage 1: QueryGenerator (Sprint 4)
10 NL queries verified for SELECT, tenant_id filter, and table mapping.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.erp.query_generator import QueryGenerator, GeneratedSQL


@pytest.fixture()
def generator() -> QueryGenerator:
    return QueryGenerator()


NL_QUERIES = [
    ("Show all open sales orders for tenant ACME",              "sales_orders"),
    ("What is the total revenue this quarter?",                 "sales_orders"),
    ("List all suppliers with outstanding invoices",            "suppliers"),
    ("Show inventory levels for warehouse WH-001",              "inventory"),
    ("How many employees are in the finance department?",       "employees"),
    ("Get all purchase orders pending approval",                "purchase_orders"),
    ("Show payroll summary for March 2025",                     "payroll"),
    ("List all active contracts expiring in the next 60 days",  "contracts"),
    ("Show delayed shipments for the last 30 days",             "shipments"),
    ("Which products have stock below reorder level?",          "products"),
]


class TestQueryGeneratorOffline:
    def test_generator_returns_generated_sql_object(self, generator):
        result = generator.generate("Show all open sales orders")
        assert isinstance(result, GeneratedSQL)

    def test_offline_mode_sets_used_fallback(self, generator):
        result = generator.generate("List employees in Finance")
        assert result.used_fallback is True
        assert result.model == "offline"

    @pytest.mark.parametrize("nl_query,expected_table", NL_QUERIES)
    def test_generated_sql_contains_select(self, generator, nl_query, expected_table):
        result = generator.generate(nl_query)
        assert result.raw_sql.upper().startswith("SELECT"), (
            f"Expected SELECT for: {nl_query}\nGot: {result.raw_sql}"
        )

    @pytest.mark.parametrize("nl_query,expected_table", NL_QUERIES)
    def test_generated_sql_always_has_tenant_filter(self, generator, nl_query, expected_table):
        import re
        result = generator.generate(nl_query)
        assert re.search(r"tenant_id\s*=", result.raw_sql, re.IGNORECASE), (
            f"Missing tenant_id filter for: {nl_query}\nSQL: {result.raw_sql}"
        )

    @pytest.mark.parametrize("nl_query,expected_table", NL_QUERIES)
    def test_generated_sql_maps_to_correct_table(self, generator, nl_query, expected_table):
        result = generator.generate(nl_query)
        assert expected_table in result.raw_sql.lower(), (
            f"Expected table '{expected_table}' for: {nl_query}\nSQL: {result.raw_sql}"
        )

    def test_latency_ms_is_recorded(self, generator):
        result = generator.generate("Show all sales orders")
        assert result.latency_ms >= 0.0

    def test_nl_query_preserved_in_result(self, generator):
        nl = "List all overdue invoices for tenant FERZA"
        result = generator.generate(nl)
        assert result.nl_query == nl

    def test_aggregation_added_for_total_queries(self, generator):
        result = generator.generate("What is the total revenue this month?")
        assert "SUM" in result.raw_sql.upper()

    def test_limit_added_for_top_n_queries(self, generator):
        result = generator.generate("Show top 10 customers by order value")
        assert "LIMIT" in result.raw_sql.upper()

    def test_stage1_metric_increments(self, generator):
        from prometheus_client import REGISTRY
        before = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage1_latency_seconds_count"
        )
        generator.generate("Show all employees in HR")
        after = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage1_latency_seconds_count"
        )
        assert after > before
