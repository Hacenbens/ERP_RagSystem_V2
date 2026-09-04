"""
SQL Pipeline — Stage 3: Query Executor
ValidationReport → ExecutionResult

Architecture rules (HARD — never violate):
  1. MUST check report.has_tenant_filter before executing. Raises if False.
  2. Only executes when report.can_execute is True.
  3. Every ExecutionResult gets a unique query_id logged to MongoDB.
  4. SQL is read-only (enforced by Stage 2 — SELECT only).

Real implementation connects to ERP PostgreSQL (read-only).
Falls back to InMemoryExecutor when PG_HOST is unavailable (tests / CI).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from helpers.config import erp_pg_dsn
from src.observability.prometheus_metrics import SQL_PIPELINE_ERRORS, SQL_STAGE3_ROWS
from src.infrastructure.erp.query_log_repository import (
    InMemoryQueryLogRepository,
    QueryLogEntry,
)
from src.infrastructure.erp.query_validator import ValidationReport
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class TenantFilterMissingError(ValueError):
    """Raised when Stage 3 receives a report without a tenant_id filter.

    This should NEVER happen in production — Stage 2 must gate this.
    """


class SQLExecutionError(Exception):
    """Raised when the SQL execution itself fails."""


class PostgresDriverMissingError(RuntimeError):
    """Raised when a database is configured but psycopg2 is not installed."""


@dataclass
class ExecutionResult:
    """Output of Stage 3."""
    query_id: str
    sql: str
    tenant_id: str
    rows: list[dict[str, Any]]
    row_count: int
    latency_ms: float
    columns: list[str] = field(default_factory=list)
    error: Optional[str] = None
    executor: str = "in_memory"

    @property
    def synthetic(self) -> bool:
        """True when these rows were invented rather than read from the ERP.

        InMemoryExecutor returns hardcoded values — 1_500_000.0 for any
        SUM(amount), two fixed sales orders, two fixed employees. Presenting
        those as ERP figures is the most dangerous thing this pipeline can
        do, so every layer above carries this flag.
        """
        return self.executor != "postgresql"

    @property
    def success(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# In-memory executor (tests / CI — no real PG needed)
# ---------------------------------------------------------------------------

class InMemoryExecutor:
    """Returns synthetic rows based on SQL keywords. Used in tests."""

    def execute(self, sql: str, params: dict) -> list[dict]:
        sql_lower = sql.lower()
        tenant_id = params.get("tenant_id", "test-tenant")

        if "count(*)" in sql_lower or "count(" in sql_lower:
            return [{"record_count": 42, "tenant_id": tenant_id}]
        if "sum(amount)" in sql_lower:
            return [{"total_amount": 1_500_000.0, "tenant_id": tenant_id}]
        if "sales_orders" in sql_lower:
            return [
                {"order_id": "SO-001", "amount": 50000.0, "status": "open", "tenant_id": tenant_id},
                {"order_id": "SO-002", "amount": 75000.0, "status": "pending", "tenant_id": tenant_id},
            ]
        if "employees" in sql_lower:
            return [
                {"employee_id": "EMP-001", "name": "Alice", "department": "Finance", "tenant_id": tenant_id},
                {"employee_id": "EMP-002", "name": "Bob", "department": "HR", "tenant_id": tenant_id},
            ]
        if "inventory" in sql_lower or "products" in sql_lower:
            return [
                {"product_id": "SKU-001", "stock": 150, "reorder_level": 50, "tenant_id": tenant_id},
            ]
        # Generic fallback
        return [{"id": "row-001", "tenant_id": tenant_id, "value": "synthetic_result"}]


# ---------------------------------------------------------------------------
# PostgreSQL executor (production)
# ---------------------------------------------------------------------------

_NAMED_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")
_SINGLE_QUOTED_RE = re.compile(r"'(?:[^']|'')*'")


def to_pyformat(sql: str) -> str:
    """Rewrite ``:name`` placeholders as psycopg2's ``%(name)s``.

    The pipeline speaks one placeholder style end to end — QueryGenerator emits
    ``WHERE tenant_id = :tenant_id`` and QueryValidator checks for exactly that
    — but psycopg2 only understands pyformat. Passing the SQL through
    unchanged sent a literal colon to the server:

        syntax error at or near ":"
        LINE 1: ... FROM sales_orders WHERE tenant_id = :tenant_id

    Every query against a real database failed that way, and because the
    executor logs the error and returns an empty result rather than raising,
    the API answered 200 with no rows and synthetic=False — reporting a total
    failure as genuine ERP data.

    Translating here rather than changing the generator keeps ``:name`` as the
    pipeline's own vocabulary and makes paramstyle what it should be: a detail
    of the driver adapter. InMemoryExecutor is unaffected.

    Two hazards handled:

    - ``::`` casts. ``created_at::date`` must survive; the lookbehind stops the
      second colon matching, and the first cannot because a colon does not
      start an identifier.
    - Literal ``%``. Once any parameters are passed, psycopg2 treats ``%`` in
      the SQL as a format character, so ``LIKE '%draft%'`` raises
      IndexError. Percent signs are doubled first, everywhere, then
      placeholders are substituted outside quoted strings only — so a colon
      inside a string literal is left alone.
    """
    out: list[str] = []
    last = 0
    for match in _SINGLE_QUOTED_RE.finditer(sql):
        out.append(_NAMED_PARAM_RE.sub(r"%(\1)s", sql[last:match.start()].replace("%", "%%")))
        out.append(match.group(0).replace("%", "%%"))  # literal: escape only
        last = match.end()
    out.append(_NAMED_PARAM_RE.sub(r"%(\1)s", sql[last:].replace("%", "%%")))
    return "".join(out)


class PostgreSQLExecutor:
    """Executes read-only SQL against the ERP PostgreSQL instance."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def execute(self, sql: str, params: dict) -> list[dict]:
        try:
            import psycopg2  # type: ignore
            import psycopg2.extras  # type: ignore
            with psycopg2.connect(self._dsn) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(to_pyformat(sql), params)
                    return [dict(row) for row in cur.fetchall()]
        except ImportError:
            raise SQLExecutionError("psycopg2 not installed — cannot connect to PostgreSQL.")


# ---------------------------------------------------------------------------
# QueryExecutor — Stage 3 orchestrator
# ---------------------------------------------------------------------------

class QueryExecutor:
    """Stage 3 — executes validated SQL and logs every result.

    Args:
        query_log: repository for logging ExecutionResults (MongoDB or in-memory)
        pg_dsn: PostgreSQL DSN string. If None or DB unreachable, uses InMemoryExecutor.
    """

    def __init__(
        self,
        query_log=None,
        pg_dsn: Optional[str] = None,
    ) -> None:
        self._log = query_log or InMemoryQueryLogRepository()
        # erp_pg_dsn() assembles ERP_PG_HOST/PORT/DATABASE/USER/PASSWORD.
        # The old code read an ERP_PG_DSN variable that is set nowhere, so
        # this always fell through to InMemoryExecutor.
        self._pg_dsn = pg_dsn if pg_dsn is not None else erp_pg_dsn()
        self._executor = self._build_executor()
        self._executor_name = (
            "postgresql" if isinstance(self._executor, PostgreSQLExecutor) else "in_memory"
        )
        if self._executor_name == "in_memory":
            logger.warning(
                "sql.stage3.synthetic_executor — no ERP_PG_PASSWORD configured; "
                "results are synthetic and must not be presented as ERP data"
            )

    @property
    def executor_name(self) -> str:
        """Which backend answers queries: "postgresql" or "in_memory"."""
        return self._executor_name

    def _build_executor(self):
        if self._pg_dsn:
            self._require_psycopg2()
            try:
                return PostgreSQLExecutor(self._pg_dsn)
            except Exception:
                logger.error("sql.stage3.pg_connect_failed — falling back to synthetic rows")
        return InMemoryExecutor()

    @staticmethod
    def _require_psycopg2() -> None:
        """Fail startup when a database is configured but the driver is missing.

        PostgreSQLExecutor imports psycopg2 inside execute(), so without the
        driver the executor was still selected: executor_name became
        "postgresql", every query returned zero rows with
        "psycopg2 not installed", and .synthetic was False — the API reported
        an empty result as real ERP data. Claiming provenance the system
        cannot deliver is worse than either failing or answering synthetically,
        so this is checked once, up front.
        """
        try:
            import psycopg2  # noqa: F401
        except ImportError as exc:
            raise PostgresDriverMissingError(
                "ERP PostgreSQL is configured (ERP_PG_PASSWORD is set) but "
                "psycopg2 is not installed. Install it with "
                "`pip install -r requirements.txt`, or clear ERP_PG_PASSWORD "
                "to run on synthetic rows flagged synthetic: true."
            ) from exc

    def execute(
        self,
        report: ValidationReport,
        tenant_id: str,
    ) -> ExecutionResult:
        """Execute the validated SQL and return an ExecutionResult.

        CRITICAL: raises TenantFilterMissingError if report.has_tenant_filter is False.
        This is the last line of defence before SQL hits the database.
        """
        # --- HARD GATE: tenant filter check ----------------------------------
        if not report.has_tenant_filter:
            raise TenantFilterMissingError(
                "Stage 3 refuses to execute: ValidationReport.has_tenant_filter=False. "
                "All ERP queries must include WHERE tenant_id = :tenant_id."
            )

        if not report.can_execute:
            raise ValueError(
                f"Stage 3 refuses to execute invalid SQL. "
                f"Validation errors: {report.errors}"
            )

        query_id = str(uuid4())
        t0 = time.perf_counter()

        try:
            rows = self._executor.execute(
                report.sanitized_sql,
                params={"tenant_id": tenant_id},
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            columns = list(rows[0].keys()) if rows else []

            result = ExecutionResult(
                query_id=query_id,
                sql=report.sanitized_sql,
                tenant_id=tenant_id,
                rows=rows,
                row_count=len(rows),
                latency_ms=latency_ms,
                columns=columns,
                executor=self._executor_name,
            )
            SQL_STAGE3_ROWS.observe(len(rows))
            logger.info(
                "sql.stage3.executed",
                query_id=query_id,
                row_count=len(rows),
                latency_ms=round(latency_ms, 2),
            )

        except TenantFilterMissingError:
            raise
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            SQL_PIPELINE_ERRORS.labels(stage="stage3").inc()
            result = ExecutionResult(
                query_id=query_id,
                sql=report.sanitized_sql,
                tenant_id=tenant_id,
                rows=[],
                row_count=0,
                latency_ms=latency_ms,
                error=str(exc),
                executor=self._executor_name,
            )
            logger.error("sql.stage3.execution_error", query_id=query_id, error=str(exc))

        # Log every execution to MongoDB (or in-memory in tests)
        self._log.save(QueryLogEntry(
            query_id=query_id,
            nl_query=report.raw_sql,
            sql=report.sanitized_sql,
            tenant_id=tenant_id,
            row_count=result.row_count,
            latency_ms=result.latency_ms,
            error=result.error,
        ))

        return result


__all__ = [
    "QueryExecutor",
    "to_pyformat",
    "PostgresDriverMissingError",
    "ExecutionResult",
    "TenantFilterMissingError",
    "SQLExecutionError",
    "InMemoryExecutor",
]
