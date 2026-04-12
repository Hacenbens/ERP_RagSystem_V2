"""
SQL Pipeline — Stage 2: Query Validator
Raw SQL → ValidationReport

Architecture rules (non-negotiable):
  1. ValidationReport.has_tenant_filter MUST be True before Stage 3 runs.
  2. All non-SELECT SQL (INSERT/UPDATE/DELETE/DROP/DDL) is rejected here.
  3. Stage 3 must never receive a report with has_tenant_filter=False.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.observability.prometheus_metrics import SQL_PIPELINE_ERRORS, SQL_STAGE2_ERRORS
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class ValidationError(Exception):
    """Raised when a SQL query fails a hard validation rule."""


# ---------------------------------------------------------------------------
# Forbidden SQL patterns — DDL, DML writes, dangerous functions
# ---------------------------------------------------------------------------

_FORBIDDEN_STATEMENTS: tuple[str, ...] = (
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bTRUNCATE\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bREPLACE\b",
    r"\bMERGE\b",
    r"\bEXEC\b",
    r"\bEXECUTE\b",
    r"\bCALL\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
)

# SQL injection patterns
_INJECTION_PATTERNS: tuple[str, ...] = (
    r";\s*\w",                        # stacked queries
    r"--",                             # line comments
    r"/\*",                            # block comments
    r"\bUNION\b",                      # UNION-based injection
    r"\bxp_\w+",                       # SQL Server extended procs
    r"SLEEP\s*\(",                     # time-based blind injection
    r"BENCHMARK\s*\(",                 # MySQL BENCHMARK
    r"LOAD_FILE\s*\(",                 # file read
    r"INTO\s+OUTFILE",                 # file write
    r"INFORMATION_SCHEMA",             # schema enumeration
    r"PG_SLEEP\s*\(",                  # PostgreSQL sleep
    r"PG_READ_FILE\s*\(",              # PostgreSQL file read
)

_TENANT_FILTER_PATTERN = re.compile(
    r"tenant_id\s*=\s*[:$]tenant_id|tenant_id\s*=\s*'[^']+'",
    re.IGNORECASE,
)

_SELECT_PATTERN = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


@dataclass
class ValidationReport:
    """Output of Stage 2 — the gate before Stage 3 execution.

    Architecture rule: Stage 3 MUST check has_tenant_filter before executing.
    """
    raw_sql: str
    is_valid: bool
    has_tenant_filter: bool
    is_select_only: bool
    sanitized_sql: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def can_execute(self) -> bool:
        """True only if valid AND has_tenant_filter — the only safe gate."""
        return self.is_valid and self.has_tenant_filter


class QueryValidator:
    """Stage 2 — validates and sanitizes raw SQL before execution.

    All validation failures populate ValidationReport.errors.
    A report with can_execute=False must NEVER reach Stage 3.
    """

    def validate(self, raw_sql: str) -> ValidationReport:
        errors: list[str] = []
        warnings: list[str] = []

        # --- Rule 1: Must be SELECT -------------------------------------------
        is_select = bool(_SELECT_PATTERN.match(raw_sql))
        if not is_select:
            errors.append("Only SELECT statements are permitted.")

        # --- Rule 2: No forbidden write/DDL statements ------------------------
        for pattern in _FORBIDDEN_STATEMENTS:
            if re.search(pattern, raw_sql, re.IGNORECASE):
                keyword = re.search(pattern, raw_sql, re.IGNORECASE).group()
                errors.append(f"Forbidden SQL keyword: {keyword.upper()}")

        # --- Rule 3: No injection patterns ------------------------------------
        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, raw_sql, re.IGNORECASE):
                errors.append(f"Potential SQL injection pattern detected: {pattern}")

        # --- Rule 4: tenant_id filter (CRITICAL) ------------------------------
        has_tenant = bool(_TENANT_FILTER_PATTERN.search(raw_sql))
        if not has_tenant:
            errors.append(
                "Missing tenant_id filter. All ERP queries MUST include "
                "WHERE tenant_id = :tenant_id to enforce tenant isolation."
            )

        # --- Rule 5: No wildcard SELECT * on joins ----------------------------
        if re.search(r"SELECT\s+\*", raw_sql, re.IGNORECASE) and re.search(
            r"\bJOIN\b", raw_sql, re.IGNORECASE
        ):
            warnings.append("SELECT * with JOIN may return unexpected columns.")

        # --- Rule 6: LIMIT recommended on large tables ------------------------
        if not re.search(r"\bLIMIT\b", raw_sql, re.IGNORECASE) and not re.search(
            r"\bCOUNT\s*\(", raw_sql, re.IGNORECASE
        ):
            warnings.append("Consider adding LIMIT to prevent large result sets.")

        is_valid = len(errors) == 0
        sanitized = self._sanitize(raw_sql) if is_valid else raw_sql

        report = ValidationReport(
            raw_sql=raw_sql,
            is_valid=is_valid,
            has_tenant_filter=has_tenant,
            is_select_only=is_select,
            sanitized_sql=sanitized,
            errors=errors,
            warnings=warnings,
        )

        if not is_valid:
            for err in errors:
                reason = (
                    "no_tenant_filter" if "tenant_id" in err
                    else "forbidden_statement" if "Forbidden" in err
                    else "injection_pattern" if "injection" in err
                    else "other"
                )
                SQL_STAGE2_ERRORS.labels(reason=reason).inc()
            SQL_PIPELINE_ERRORS.labels(stage="stage2").inc()
            logger.warning(
                "sql.stage2.validation_failed",
                errors=errors,
                has_tenant_filter=has_tenant,
            )
        else:
            logger.info(
                "sql.stage2.validation_passed",
                has_tenant_filter=has_tenant,
                warnings=warnings,
            )

        return report

    def _sanitize(self, sql: str) -> str:
        """Light sanitization: strip trailing semicolons and extra whitespace."""
        sql = sql.strip()
        sql = re.sub(r";+\s*$", "", sql)        # remove trailing semicolons
        sql = re.sub(r"\s+", " ", sql)           # collapse whitespace
        return sql


__all__ = ["QueryValidator", "ValidationReport", "ValidationError"]
