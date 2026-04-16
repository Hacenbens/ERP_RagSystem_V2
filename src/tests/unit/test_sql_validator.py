"""
Unit tests — SQL Validator / Stage 2 (Sprint 4)
Covers every validation rule in QueryValidator.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.erp.query_validator import QueryValidator, ValidationReport


@pytest.fixture()
def validator() -> QueryValidator:
    return QueryValidator()


# ---------------------------------------------------------------------------
# Rule 1: Only SELECT is allowed
# ---------------------------------------------------------------------------

class TestSelectOnlyRule:
    def test_valid_select_passes(self, validator):
        report = validator.validate(
            "SELECT * FROM sales_orders WHERE tenant_id = :tenant_id"
        )
        assert report.is_select_only is True
        assert "Only SELECT" not in " ".join(report.errors)

    def test_insert_is_rejected(self, validator):
        sql = "INSERT INTO sales_orders (tenant_id) VALUES ('x')"
        report = validator.validate(sql)
        assert report.is_select_only is False
        assert not report.is_valid
        assert any("SELECT" in e for e in report.errors)

    def test_update_is_rejected(self, validator):
        report = validator.validate(
            "UPDATE sales_orders SET status = 'closed' WHERE tenant_id = :tenant_id"
        )
        assert not report.is_valid

    def test_delete_is_rejected(self, validator):
        report = validator.validate(
            "DELETE FROM sales_orders WHERE tenant_id = :tenant_id"
        )
        assert not report.is_valid

    def test_drop_is_rejected(self, validator):
        report = validator.validate("DROP TABLE sales_orders")
        assert not report.is_valid

    def test_truncate_is_rejected(self, validator):
        report = validator.validate("TRUNCATE TABLE sales_orders")
        assert not report.is_valid

    def test_alter_is_rejected(self, validator):
        report = validator.validate("ALTER TABLE sales_orders ADD COLUMN foo TEXT")
        assert not report.is_valid

    def test_create_is_rejected(self, validator):
        report = validator.validate("CREATE TABLE foo (id TEXT)")
        assert not report.is_valid

    def test_select_case_insensitive(self, validator):
        report = validator.validate(
            "select * from employees where tenant_id = :tenant_id"
        )
        assert report.is_select_only is True


# ---------------------------------------------------------------------------
# Rule 2: Forbidden write/DDL keywords anywhere in query
# ---------------------------------------------------------------------------

class TestForbiddenKeywords:
    @pytest.mark.parametrize("keyword", [
        "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
        "ALTER", "CREATE", "REPLACE", "MERGE", "EXEC",
    ])
    def test_forbidden_keyword_blocked(self, validator, keyword):
        sql = f"SELECT * FROM t WHERE tenant_id = :tenant_id -- {keyword} here"
        report = validator.validate(sql)
        # Line comment is itself a forbidden pattern, but keyword check also fires
        assert not report.is_valid


# ---------------------------------------------------------------------------
# Rule 3: SQL injection patterns blocked
# ---------------------------------------------------------------------------

class TestInjectionPatterns:
    def test_stacked_queries_blocked(self, validator):
        sql = "SELECT * FROM t WHERE tenant_id = :tenant_id; DROP TABLE t"
        report = validator.validate(sql)
        assert not report.is_valid

    def test_line_comment_blocked(self, validator):
        sql = "SELECT * FROM t WHERE tenant_id = :tenant_id -- comment"
        report = validator.validate(sql)
        assert not report.is_valid

    def test_block_comment_blocked(self, validator):
        sql = "SELECT /* comment */ * FROM t WHERE tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert not report.is_valid

    def test_union_blocked(self, validator):
        sql = (
            "SELECT * FROM t WHERE tenant_id = :tenant_id "
            "UNION SELECT * FROM users"
        )
        report = validator.validate(sql)
        assert not report.is_valid

    def test_pg_sleep_blocked(self, validator):
        sql = "SELECT PG_SLEEP(5) FROM t WHERE tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert not report.is_valid

    def test_information_schema_blocked(self, validator):
        sql = "SELECT * FROM INFORMATION_SCHEMA.tables WHERE tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert not report.is_valid


# ---------------------------------------------------------------------------
# Rule 4: tenant_id filter — CRITICAL
# ---------------------------------------------------------------------------

class TestTenantFilterRule:
    def test_tenant_filter_present_passes(self, validator):
        sql = "SELECT * FROM sales_orders WHERE tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert report.has_tenant_filter is True
        assert not any("tenant_id" in e for e in report.errors)

    def test_missing_tenant_filter_fails(self, validator):
        sql = "SELECT * FROM sales_orders WHERE status = 'open'"
        report = validator.validate(sql)
        assert report.has_tenant_filter is False
        assert not report.is_valid
        assert any("tenant_id" in e for e in report.errors)

    def test_tenant_filter_with_literal_value(self, validator):
        sql = "SELECT * FROM sales_orders WHERE tenant_id = 'FERZA'"
        report = validator.validate(sql)
        assert report.has_tenant_filter is True

    def test_tenant_filter_case_insensitive(self, validator):
        sql = "SELECT * FROM t WHERE TENANT_ID = :tenant_id"
        report = validator.validate(sql)
        assert report.has_tenant_filter is True

    def test_has_tenant_filter_false_blocks_can_execute(self, validator):
        sql = "SELECT * FROM sales_orders WHERE status = 'open'"
        report = validator.validate(sql)
        assert report.can_execute is False


# ---------------------------------------------------------------------------
# can_execute gate logic
# ---------------------------------------------------------------------------

class TestCanExecuteGate:
    def test_valid_select_with_tenant_filter_can_execute(self, validator):
        sql = "SELECT * FROM employees WHERE tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert report.can_execute is True

    def test_invalid_sql_cannot_execute(self, validator):
        sql = "DROP TABLE employees"
        report = validator.validate(sql)
        assert report.can_execute is False

    def test_missing_tenant_cannot_execute(self, validator):
        sql = "SELECT * FROM employees WHERE department = 'Finance'"
        report = validator.validate(sql)
        assert report.can_execute is False

    def test_can_execute_requires_both_valid_and_tenant(self, validator):
        """can_execute = is_valid AND has_tenant_filter — both required."""
        good_sql = "SELECT id FROM t WHERE tenant_id = :tenant_id"
        report = validator.validate(good_sql)
        assert report.is_valid is True
        assert report.has_tenant_filter is True
        assert report.can_execute is True


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

class TestSanitization:
    def test_trailing_semicolon_removed(self, validator):
        sql = "SELECT * FROM t WHERE tenant_id = :tenant_id;"
        report = validator.validate(sql)
        assert report.sanitized_sql.endswith(":tenant_id")
        assert ";" not in report.sanitized_sql

    def test_multiple_trailing_semicolons_removed(self, validator):
        sql = "SELECT * FROM t WHERE tenant_id = :tenant_id;;;"
        report = validator.validate(sql)
        assert ";" not in report.sanitized_sql

    def test_whitespace_collapsed(self, validator):
        sql = "SELECT   *   FROM   t   WHERE   tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert "  " not in report.sanitized_sql

    def test_invalid_sql_not_sanitized(self, validator):
        sql = "DROP TABLE t"
        report = validator.validate(sql)
        assert report.sanitized_sql == sql  # unchanged on failure


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_select_star_with_join_generates_warning(self, validator):
        sql = (
            "SELECT * FROM orders o "
            "JOIN customers c ON o.customer_id = c.id "
            "WHERE o.tenant_id = :tenant_id"
        )
        report = validator.validate(sql)
        assert report.is_valid is True
        assert any("SELECT *" in w or "JOIN" in w for w in report.warnings)

    def test_missing_limit_on_plain_select_generates_warning(self, validator):
        sql = "SELECT id, name FROM employees WHERE tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert any("LIMIT" in w for w in report.warnings)

    def test_count_query_no_limit_warning(self, validator):
        sql = "SELECT COUNT(*) FROM employees WHERE tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert not any("LIMIT" in w for w in report.warnings)

    def test_valid_query_with_no_issues_has_no_errors(self, validator):
        sql = (
            "SELECT id, name FROM employees "
            "WHERE tenant_id = :tenant_id AND department = 'Finance' LIMIT 50"
        )
        report = validator.validate(sql)
        assert report.errors == []
        assert report.is_valid is True


# ---------------------------------------------------------------------------
# ValidationReport structure
# ---------------------------------------------------------------------------

class TestValidationReportStructure:
    def test_report_has_all_fields(self, validator):
        sql = "SELECT * FROM t WHERE tenant_id = :tenant_id"
        report = validator.validate(sql)
        assert isinstance(report, ValidationReport)
        assert report.raw_sql == sql
        assert isinstance(report.is_valid, bool)
        assert isinstance(report.has_tenant_filter, bool)
        assert isinstance(report.is_select_only, bool)
        assert isinstance(report.sanitized_sql, str)
        assert isinstance(report.errors, list)
        assert isinstance(report.warnings, list)

    def test_error_accumulates_multiple_issues(self, validator):
        # Missing SELECT + missing tenant_id → multiple errors
        sql = "UPDATE t SET x = 1"
        report = validator.validate(sql)
        assert len(report.errors) >= 2  # at least: non-SELECT + missing tenant_id
