"""
Integration tests — Stage 3: QueryExecutor (Sprint 4)
Uses InMemoryExecutor — no real PostgreSQL required.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.erp.query_executor import (
    ExecutionResult,
    QueryExecutor,
    TenantFilterMissingError,
)
from src.infrastructure.erp.query_log_repository import InMemoryQueryLogRepository
from src.infrastructure.erp.query_validator import QueryValidator


@pytest.fixture()
def log_repo():
    return InMemoryQueryLogRepository()


@pytest.fixture()
def executor(log_repo):
    return QueryExecutor(query_log=log_repo)


@pytest.fixture()
def validator():
    return QueryValidator()


def _valid_report(validator, sql=None):
    sql = sql or "SELECT * FROM sales_orders WHERE tenant_id = :tenant_id"
    return validator.validate(sql)


class TestExecutionResult:
    def test_execution_returns_result_object(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        assert isinstance(result, ExecutionResult)

    def test_result_has_unique_query_id(self, executor, validator):
        report = _valid_report(validator)
        r1 = executor.execute(report, tenant_id="FERZA")
        r2 = executor.execute(report, tenant_id="FERZA")
        assert r1.query_id != r2.query_id

    def test_query_id_is_non_empty(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        assert result.query_id and len(result.query_id) > 0

    def test_result_tenant_id_matches_input(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="ACME")
        assert result.tenant_id == "ACME"

    def test_result_sql_matches_sanitized_sql(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        assert result.sql == report.sanitized_sql

    def test_result_latency_ms_recorded(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        assert result.latency_ms >= 0.0

    def test_success_flag_true_on_clean_execution(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        assert result.success is True
        assert result.error is None

    def test_rows_returned_as_list_of_dicts(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        assert isinstance(result.rows, list)
        for row in result.rows:
            assert isinstance(row, dict)

    def test_row_count_matches_rows_length(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        assert result.row_count == len(result.rows)

    def test_columns_populated_when_rows_returned(self, executor, validator):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        if result.row_count > 0:
            assert len(result.columns) > 0


class TestQueryLogging:
    def test_every_execution_is_logged(self, executor, validator, log_repo):
        report = _valid_report(validator)
        executor.execute(report, tenant_id="FERZA")
        assert log_repo.count() == 1

    def test_log_entry_has_correct_query_id(self, executor, validator, log_repo):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        entry = log_repo.get_by_id(result.query_id)
        assert entry is not None
        assert entry.query_id == result.query_id

    def test_log_entry_has_correct_tenant_id(self, executor, validator, log_repo):
        report = _valid_report(validator)
        executor.execute(report, tenant_id="ACME")
        entries = log_repo.get_all()
        assert entries[-1].tenant_id == "ACME"

    def test_multiple_executions_all_logged(self, executor, validator, log_repo):
        report = _valid_report(validator)
        for _ in range(3):
            executor.execute(report, tenant_id="FERZA")
        assert log_repo.count() == 3

    def test_log_entry_has_row_count(self, executor, validator, log_repo):
        report = _valid_report(validator)
        result = executor.execute(report, tenant_id="FERZA")
        entry = log_repo.get_by_id(result.query_id)
        assert entry.row_count == result.row_count


class TestTenantGuardInExecutor:
    def test_missing_tenant_filter_raises_before_db_call(self, executor, validator):
        sql = "SELECT * FROM employees WHERE department = 'Finance'"
        report = validator.validate(sql)
        with pytest.raises(TenantFilterMissingError):
            executor.execute(report, tenant_id="FERZA")

    def test_invalid_report_raises_value_error(self, executor, validator):
        sql = "DROP TABLE employees"
        report = validator.validate(sql)
        with pytest.raises((TenantFilterMissingError, ValueError)):
            executor.execute(report, tenant_id="FERZA")


class TestInMemoryExecutorTablePatterns:
    def test_sales_orders_returns_order_rows(self, executor, validator):
        report = _valid_report(
            validator, "SELECT * FROM sales_orders WHERE tenant_id = :tenant_id"
        )
        result = executor.execute(report, tenant_id="FERZA")
        assert result.row_count > 0
        assert any("order_id" in r for r in result.rows)

    def test_employees_returns_employee_rows(self, executor, validator):
        report = _valid_report(
            validator, "SELECT * FROM employees WHERE tenant_id = :tenant_id"
        )
        result = executor.execute(report, tenant_id="FERZA")
        assert result.row_count > 0
        assert any("employee_id" in r for r in result.rows)

    def test_count_query_returns_count_row(self, executor, validator):
        report = _valid_report(
            validator,
            "SELECT COUNT(*) AS record_count FROM sales_orders WHERE tenant_id = :tenant_id",
        )
        result = executor.execute(report, tenant_id="ACME")
        assert result.row_count > 0
        assert any("record_count" in r for r in result.rows)

    def test_stage3_rows_metric_increments(self, executor, validator):
        from prometheus_client import REGISTRY
        before = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage3_rows_returned_count"
        )
        report = _valid_report(validator)
        executor.execute(report, tenant_id="FERZA")
        after = sum(
            s.value for m in REGISTRY.collect() for s in m.samples
            if s.name == "erp_rag_sql_stage3_rows_returned_count"
        )
        assert after > before
