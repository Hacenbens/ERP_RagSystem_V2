"""
The SQL pipeline against a real PostgreSQL replica — Sprint 11 (G1·5).

Until now the SQL pipeline had never executed against an actual database. The
first attempt failed on every query:

    syntax error at or near ":"
    LINE 1: ... total_amount FROM sales_orders WHERE tenant_id = :tenant_id

QueryGenerator emits ``:tenant_id`` and QueryValidator requires exactly that,
but psycopg2 only understands ``%(name)s``. The SQL went to the server
unchanged. Worse, the executor logs the error and returns an empty result
rather than raising, so the API answered 200 with no rows and
``synthetic: false`` — reporting a total failure as genuine ERP data.

The unit tests below cover the translation. The integration tests run against
a seeded container and are skipped without one:

    docker run -d --name erp_rag_pg_dev -e POSTGRES_DB=erp_prod \\
      -e POSTGRES_USER=erp_admin -e POSTGRES_PASSWORD=… -p 55432:5432 \\
      -v ./docker/dev-data/erp_seed.sql:/docker-entrypoint-initdb.d/01.sql:ro \\
      postgres:16-alpine
    ERP_PG_TEST_DSN=postgresql://erp_readonly:…@127.0.0.1:55432/erp_prod pytest …
"""
from __future__ import annotations

import os

import pytest

from src.infrastructure.erp.query_executor import QueryExecutor, to_pyformat
from src.infrastructure.erp.query_generator import QueryGenerator
from src.infrastructure.erp.query_validator import QueryValidator

TEST_DSN = os.environ.get("ERP_PG_TEST_DSN", "")


class TestParamstyleTranslation:
    """Pure translation — no database needed."""

    def test_named_placeholder_becomes_pyformat(self):
        assert to_pyformat("WHERE tenant_id = :tenant_id") == (
            "WHERE tenant_id = %(tenant_id)s"
        )

    def test_postgres_casts_survive(self):
        """``created_at::date`` must not be mangled into a placeholder."""
        assert to_pyformat("SELECT created_at::date FROM t") == (
            "SELECT created_at::date FROM t"
        )

    def test_cast_alongside_a_placeholder(self):
        assert to_pyformat("SELECT a::text FROM t WHERE x = :tenant_id") == (
            "SELECT a::text FROM t WHERE x = %(tenant_id)s"
        )

    def test_literal_percent_is_escaped(self):
        """psycopg2 treats % as a format character once params are passed."""
        assert to_pyformat("WHERE note LIKE '%draft%'") == (
            "WHERE note LIKE '%%draft%%'"
        )

    def test_a_colon_inside_a_string_literal_is_left_alone(self):
        assert to_pyformat("WHERE label = 'a:b'") == "WHERE label = 'a:b'"

    def test_multiple_placeholders(self):
        assert to_pyformat("WHERE a = :one AND b = :two") == (
            "WHERE a = %(one)s AND b = %(two)s"
        )

    def test_sql_without_placeholders_is_unchanged(self):
        assert to_pyformat("SELECT 1 FROM t") == "SELECT 1 FROM t"

    def test_the_generator_output_translates(self):
        """Ties the translation to what the pipeline actually produces."""
        raw = QueryGenerator().generate("total revenue from sales orders").raw_sql

        assert ":tenant_id" in raw
        assert "%(tenant_id)s" in to_pyformat(raw)


@pytest.mark.skipif(not TEST_DSN, reason="ERP_PG_TEST_DSN not set — needs a seeded replica")
class TestAgainstARealReplica:
    @pytest.fixture()
    def executor(self) -> QueryExecutor:
        return QueryExecutor(pg_dsn=TEST_DSN)

    def _run(self, executor: QueryExecutor, question: str, tenant: str):
        sql = QueryGenerator().generate(question).raw_sql
        return executor.execute(QueryValidator().validate(sql), tenant_id=tenant)

    def test_the_postgres_executor_is_selected(self, executor):
        assert executor.executor_name == "postgresql"

    def test_a_generated_query_returns_real_rows(self, executor):
        result = self._run(executor, "total revenue from sales orders", "ferza")

        assert result.error is None, result.error
        assert result.rows

    def test_results_from_a_real_database_are_not_flagged_synthetic(self, executor):
        result = self._run(executor, "total revenue from sales orders", "ferza")

        assert result.synthetic is False
        assert result.executor == "postgresql"

    def test_an_aggregate_groups_correctly(self, executor):
        result = self._run(executor, "count employees by department", "ferza")

        assert result.error is None
        assert {row["department"] for row in result.rows} >= {"Finance", "HR"}

    def test_tenant_filter_actually_scopes_the_data(self, executor):
        """The tenant filter is bound as a parameter, not interpolated."""
        ferza = self._run(executor, "total revenue from sales orders", "ferza")
        acme = self._run(executor, "total revenue from sales orders", "acme")

        assert ferza.rows[0]["total_amount"] != acme.rows[0]["total_amount"]

    def test_an_unknown_tenant_sees_nothing(self, executor):
        result = self._run(executor, "total revenue from sales orders", "no-such-tenant")

        assert result.rows[0]["total_amount"] is None

    def test_the_connection_is_genuinely_read_only(self, executor):
        """Database permissions, not just the validator, block writes.

        QueryValidator would reject this first in the pipeline; here it goes
        straight to the executor to prove the credentials themselves are
        restricted.
        """
        report = QueryValidator().validate(
            "SELECT * FROM sales_orders WHERE tenant_id = :tenant_id"
        )
        report.sanitized_sql = "DELETE FROM sales_orders"

        result = executor.execute(report, tenant_id="ferza")

        assert result.error is not None
        assert "permission denied" in result.error.lower()

    def test_database_types_survive_json_serialisation(self, executor):
        """Real columns return Decimal, datetime and date, not str."""
        report = QueryValidator().validate(
            "SELECT * FROM sales_orders WHERE tenant_id = :tenant_id"
        )
        result = executor.execute(report, tenant_id="ferza")

        from src.domain.models.sql_result import SQLResult
        from src.routes.query import _build_response

        body = _build_response(
            SQLResult(
                query=result.sql, rows=tuple(result.rows), row_count=result.row_count,
                latency_ms=result.latency_ms, executor=result.executor,
                synthetic=result.synthetic,
            )
        )

        assert body.model_dump_json()
        assert body.synthetic is False
