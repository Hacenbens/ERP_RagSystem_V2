"""
SQL result provenance — Sprint 10 (audit finding B-7).

Without a configured ERP database the SQL pipeline answers from
InMemoryExecutor, which returns hardcoded values: 1_500_000.0 for any
SUM(amount), two fixed sales orders, two fixed employees. The API returned
those as a plain HTTP 200 with no flag of any kind:

    {"intent": "SQL", "result": {"rows": [{"total_amount": 1500000.0}]}}

A business user reads that as revenue. Two causes:

  - QueryExecutor read an ERP_PG_DSN environment variable that is set nowhere,
    so it always selected InMemoryExecutor
  - nothing in the domain model or the HTTP contract distinguished an invented
    row from a real one

These tests pin the flag end to end, because the failure mode is silence.
"""
from __future__ import annotations

import pytest

from src.domain.models.sql_result import SQLResult
from src.infrastructure.erp.query_executor import (
    InMemoryExecutor,
    PostgreSQLExecutor,
    QueryExecutor,
)
from src.infrastructure.erp.query_validator import QueryValidator
from src.routes.query import _build_response

TENANT = "tenant-ferza"
SQL = "SELECT SUM(amount) AS total_amount FROM sales_orders WHERE tenant_id = :tenant_id"


@pytest.fixture()
def report():
    return QueryValidator().validate(SQL)


class TestDsnAssembly:
    """The DSN nothing ever set."""

    def test_no_password_means_no_dsn(self, monkeypatch):
        import importlib

        import helpers.config as cfg

        monkeypatch.setenv("ERP_PG_PASSWORD", "")
        importlib.reload(cfg)
        assert cfg.erp_pg_dsn() == ""

    def test_dsn_is_assembled_from_the_parts(self, monkeypatch):
        import importlib

        import helpers.config as cfg

        monkeypatch.setenv("ERP_PG_HOST", "erp-replica")
        monkeypatch.setenv("ERP_PG_PORT", "5433")
        monkeypatch.setenv("ERP_PG_DATABASE", "erp")
        monkeypatch.setenv("ERP_PG_USER", "ro")
        monkeypatch.setenv("ERP_PG_PASSWORD", "secret")
        importlib.reload(cfg)
        try:
            assert cfg.erp_pg_dsn() == "postgresql://ro:secret@erp-replica:5433/erp"
        finally:
            monkeypatch.undo()
            importlib.reload(cfg)


class TestExecutorReportsItself:
    def test_without_a_dsn_the_executor_is_in_memory(self, report):
        ex = QueryExecutor(pg_dsn="")
        assert ex.executor_name == "in_memory"
        assert isinstance(ex._executor, InMemoryExecutor)

    def test_with_a_dsn_the_executor_is_postgresql(self, report):
        ex = QueryExecutor(pg_dsn="postgresql://ro:pw@localhost:5432/erp")
        assert ex.executor_name == "postgresql"
        assert isinstance(ex._executor, PostgreSQLExecutor)

    def test_in_memory_results_are_marked_synthetic(self, report):
        result = QueryExecutor(pg_dsn="").execute(report, tenant_id=TENANT)
        assert result.executor == "in_memory"
        assert result.synthetic is True

    def test_the_synthetic_figure_is_the_hardcoded_one(self, report):
        """Names the exact value a reader would mistake for revenue."""
        result = QueryExecutor(pg_dsn="").execute(report, tenant_id=TENANT)
        assert result.rows[0]["total_amount"] == 1_500_000.0
        assert result.synthetic is True


class TestHttpResponseCarriesTheFlag:
    def test_synthetic_sql_result_sets_the_top_level_flag(self):
        body = _build_response(
            SQLResult(
                query=SQL, rows=({"total_amount": 1_500_000.0},), row_count=1,
                latency_ms=1.0, executor="in_memory", synthetic=True,
            )
        )
        assert body.synthetic is True

    def test_real_sql_result_does_not_set_the_flag(self):
        body = _build_response(
            SQLResult(
                query=SQL, rows=({"total_amount": 42.0},), row_count=1,
                latency_ms=1.0, executor="postgresql", synthetic=False,
            )
        )
        assert body.synthetic is False

    def test_flag_is_top_level_not_buried_in_result(self):
        """A caller must not have to dig for it."""
        body = _build_response(
            SQLResult(query=SQL, rows=(), row_count=0, latency_ms=1.0, synthetic=True)
        )
        assert "synthetic" in body.model_dump()

    def test_hybrid_inherits_synthetic_from_its_sql_half(self):
        from src.domain.models.hybrid_result import HybridResult

        body = _build_response(
            HybridResult.sql_fallback(
                SQLResult(
                    query=SQL, rows=({"total_amount": 1_500_000.0},), row_count=1,
                    latency_ms=1.0, executor="in_memory", synthetic=True,
                )
            )
        )
        assert body.synthetic is True, (
            "merged prose quotes the SQL figures, so a synthetic SQL branch "
            "taints the whole answer"
        )

    def test_rag_only_answer_is_never_marked_synthetic(self):
        from src.domain.models.rag_result import RAGResult

        body = _build_response(RAGResult.not_grounded())
        assert body.synthetic is False


class TestPostgresDriverIsRequired:
    """A configured database with no driver claimed real data and returned none.

    PostgreSQLExecutor imports psycopg2 inside execute(), so without the driver
    the executor was still selected: executor_name became "postgresql", every
    query returned zero rows with "psycopg2 not installed", and .synthetic was
    False. The API reported an empty failed result as genuine ERP data —
    worse than either failing or answering synthetically, because the flag
    added in this sprint was actively lying.
    """

    def test_missing_driver_fails_at_construction(self, monkeypatch):
        import builtins

        from src.infrastructure.erp.query_executor import PostgresDriverMissingError

        real_import = builtins.__import__

        def _no_psycopg2(name, *args, **kwargs):
            if name == "psycopg2":
                raise ImportError("simulated missing driver")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_psycopg2)

        with pytest.raises(PostgresDriverMissingError, match="psycopg2"):
            QueryExecutor(pg_dsn="postgresql://ro:pw@localhost:5432/erp")

    def test_the_error_says_how_to_recover(self, monkeypatch):
        import builtins

        from src.infrastructure.erp.query_executor import PostgresDriverMissingError

        real_import = builtins.__import__

        def _no_psycopg2(name, *args, **kwargs):
            if name == "psycopg2":
                raise ImportError("simulated missing driver")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_psycopg2)

        with pytest.raises(PostgresDriverMissingError) as exc:
            QueryExecutor(pg_dsn="postgresql://ro:pw@localhost:5432/erp")

        assert "requirements.txt" in str(exc.value)
        assert "ERP_PG_PASSWORD" in str(exc.value)

    def test_no_dsn_does_not_need_the_driver(self, monkeypatch):
        """CI and local runs have no database and must not require psycopg2."""
        import builtins

        real_import = builtins.__import__

        def _no_psycopg2(name, *args, **kwargs):
            if name == "psycopg2":
                raise ImportError("simulated missing driver")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_psycopg2)

        assert QueryExecutor(pg_dsn="").executor_name == "in_memory"

    def test_the_driver_is_declared_as_a_dependency(self):
        """It was imported by production code and never listed."""
        from pathlib import Path as _Path

        requirements = (
            _Path(__file__).resolve().parents[3] / "requirements.txt"
        ).read_text()

        assert "psycopg2" in requirements


class TestDefaultsAreHonest:
    def test_sql_result_defaults_to_synthetic(self):
        """An un-annotated result must claim less, not more."""
        assert SQLResult(query="", rows=(), row_count=0, latency_ms=0.0).synthetic is True
