"""
Integration tests — Stage 2 tenant guard (Sprint 4)
Verifies that missing tenant_id blocks execution before Stage 3.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.erp.query_validator import QueryValidator
from src.infrastructure.erp.query_executor import QueryExecutor, TenantFilterMissingError
from src.infrastructure.erp.query_log_repository import InMemoryQueryLogRepository


@pytest.fixture()
def validator():
    return QueryValidator()


@pytest.fixture()
def executor():
    return QueryExecutor(query_log=InMemoryQueryLogRepository())


class TestTenantFilterGuard:
    def test_sql_without_tenant_id_fails_validation(self, validator):
        sql = "SELECT * FROM sales_orders WHERE status = 'open'"
        report = validator.validate(sql)
        assert report.has_tenant_filter is False
        assert report.can_execute is False

    def test_report_with_no_tenant_filter_raises_in_executor(self, validator, executor):
        sql = "SELECT * FROM sales_orders WHERE status = 'open'"
        report = validator.validate(sql)
        assert not report.has_tenant_filter
        with pytest.raises(TenantFilterMissingError):
            executor.execute(report, tenant_id="FERZA")

    def test_tenant_filter_missing_error_message_is_clear(self, validator, executor):
        sql = "SELECT * FROM employees"
        report = validator.validate(sql)
        with pytest.raises(TenantFilterMissingError) as exc_info:
            executor.execute(report, tenant_id="ACME")
        assert "tenant_id" in str(exc_info.value).lower()

    def test_non_select_sql_blocked_before_stage3(self, validator, executor):
        for sql in [
            "INSERT INTO t (a) VALUES (1)",
            "UPDATE t SET a = 1 WHERE id = 1",
            "DELETE FROM t WHERE id = 1",
            "DROP TABLE t",
        ]:
            report = validator.validate(sql)
            assert not report.can_execute, f"Expected {sql!r} to be blocked"
            with pytest.raises((TenantFilterMissingError, ValueError)):
                executor.execute(report, tenant_id="FERZA")

    def test_stage2_error_counter_increments_on_missing_tenant(self):
        from prometheus_client import REGISTRY
        validator = QueryValidator()

        def _count():
            return sum(
                s.value for m in REGISTRY.collect() for s in m.samples
                if s.name == "erp_rag_sql_stage2_errors_total"
                and s.labels.get("reason") == "no_tenant_filter"
            )

        before = _count()
        validator.validate("SELECT * FROM employees WHERE dept = 'HR'")
        after = _count()
        assert after > before

    def test_pipeline_stages_are_independent(self, validator, executor):
        """Stage 3 only runs when Stage 2 explicitly clears it."""
        good_sql = "SELECT * FROM sales_orders WHERE tenant_id = :tenant_id"
        report = validator.validate(good_sql)
        assert report.can_execute is True
        result = executor.execute(report, tenant_id="FERZA")
        assert result.success is True

    def test_error_report_does_not_reach_stage3(self, validator, executor):
        """An invalid report must raise before any DB call."""
        sql = "SELECT * FROM t"  # no tenant filter
        report = validator.validate(sql)
        assert not report.has_tenant_filter
        # Must raise — no rows, no execution
        with pytest.raises((TenantFilterMissingError, ValueError)):
            executor.execute(report, tenant_id="test")
