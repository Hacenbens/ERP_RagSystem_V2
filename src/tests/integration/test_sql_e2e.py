"""
Integration tests — SQL Pipeline End-to-End (Sprint 4)
Full pipeline: NL query → Stage 1 → Stage 2 → Stage 3 → ExecutionResult
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.erp.query_executor import ExecutionResult, QueryExecutor, TenantFilterMissingError
from src.infrastructure.erp.query_generator import QueryGenerator
from src.infrastructure.erp.query_log_repository import InMemoryQueryLogRepository
from src.infrastructure.erp.query_validator import QueryValidator


@pytest.fixture()
def pipeline():
    log = InMemoryQueryLogRepository()
    return (
        QueryGenerator(),
        QueryValidator(),
        QueryExecutor(query_log=log),
        log,
    )


def run_pipeline(generator, validator, executor, nl_query, tenant_id="FERZA"):
    generated = generator.generate(nl_query)
    report = validator.validate(generated.raw_sql)
    result = executor.execute(report, tenant_id=tenant_id)
    return generated, report, result


E2E_QUERIES = [
    ("Show all open sales orders for tenant FERZA",         "FERZA"),
    ("How many employees are in the finance department?",   "ACME"),
    ("Show inventory levels for warehouse WH-001",          "FERZA"),
    ("Get all purchase orders pending approval",            "ACME"),
    ("Show payroll summary for March 2025",                 "FERZA"),
]


class TestFullPipeline:
    @pytest.mark.parametrize("nl_query,tenant_id", E2E_QUERIES)
    def test_full_pipeline_succeeds(self, pipeline, nl_query, tenant_id):
        gen, val, exe, log = pipeline
        generated, report, result = run_pipeline(gen, val, exe, nl_query, tenant_id)

        assert generated.raw_sql, "Stage 1 must produce SQL"
        assert report.can_execute, f"Stage 2 must clear for: {nl_query}\nErrors: {report.errors}"
        assert result.success, f"Stage 3 must succeed for: {nl_query}\nError: {result.error}"

    @pytest.mark.parametrize("nl_query,tenant_id", E2E_QUERIES)
    def test_every_result_has_query_id(self, pipeline, nl_query, tenant_id):
        gen, val, exe, log = pipeline
        _, _, result = run_pipeline(gen, val, exe, nl_query, tenant_id)
        assert result.query_id and len(result.query_id) > 10

    @pytest.mark.parametrize("nl_query,tenant_id", E2E_QUERIES)
    def test_every_execution_logged(self, pipeline, nl_query, tenant_id):
        gen, val, exe, log = pipeline
        _, _, result = run_pipeline(gen, val, exe, nl_query, tenant_id)
        assert log.get_by_id(result.query_id) is not None

    @pytest.mark.parametrize("nl_query,tenant_id", E2E_QUERIES)
    def test_tenant_id_flows_through_all_stages(self, pipeline, nl_query, tenant_id):
        gen, val, exe, log = pipeline
        _, report, result = run_pipeline(gen, val, exe, nl_query, tenant_id)
        assert report.has_tenant_filter is True
        assert result.tenant_id == tenant_id

    def test_pipeline_short_circuits_on_missing_tenant_filter(self, pipeline):
        """Stage 3 must never run when Stage 2 clears has_tenant_filter=False."""
        gen, val, exe, log = pipeline
        # Manually craft a bad report (no tenant filter)
        bad_report = val.validate("SELECT * FROM employees WHERE dept = 'HR'")
        assert not bad_report.has_tenant_filter

        with pytest.raises(TenantFilterMissingError):
            exe.execute(bad_report, tenant_id="FERZA")

        # Nothing logged — execution never happened
        assert log.count() == 0

    def test_pipeline_short_circuits_on_non_select(self, pipeline):
        gen, val, exe, log = pipeline
        bad_report = val.validate("DROP TABLE employees")
        assert not bad_report.can_execute
        with pytest.raises((TenantFilterMissingError, ValueError)):
            exe.execute(bad_report, tenant_id="FERZA")

    def test_all_5_queries_logged_independently(self, pipeline):
        gen, val, exe, log = pipeline
        for nl_query, tenant_id in E2E_QUERIES:
            try:
                run_pipeline(gen, val, exe, nl_query, tenant_id)
            except Exception:
                pass
        assert log.count() == len(E2E_QUERIES)


class TestPrometheusMetricsAcrossPipeline:
    def test_stage1_latency_recorded_after_e2e(self, pipeline):
        from prometheus_client import REGISTRY
        gen, val, exe, log = pipeline
        before = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage1_latency_seconds_count"
        )
        run_pipeline(gen, val, exe, "Show all sales orders for tenant FERZA")
        after = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage1_latency_seconds_count"
        )
        assert after > before

    def test_stage3_rows_recorded_after_e2e(self, pipeline):
        from prometheus_client import REGISTRY
        gen, val, exe, log = pipeline
        before = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage3_rows_returned_count"
        )
        run_pipeline(gen, val, exe, "Show all employees for tenant ACME", "ACME")
        after = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage3_rows_returned_count"
        )
        assert after > before

    def test_stage2_error_counter_on_bad_query(self, pipeline):
        from prometheus_client import REGISTRY
        gen, val, exe, log = pipeline
        before = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage2_errors_total"
        )
        val.validate("SELECT * FROM t WHERE department = 'HR'")  # no tenant filter
        after = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage2_errors_total"
        )
        assert after > before
