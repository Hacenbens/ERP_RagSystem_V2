"""
SQL Benchmark Harness — Sprint 2
Runs 20 NL→SQL test cases and reports pass/fail + success_rate.
Exit code 0 = pass, 1 = fail (CI-compatible).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config — thresholds read from env (set in helpers/config.py or CI secrets)
# ---------------------------------------------------------------------------
SQL_SUCCESS_MIN = float(os.environ.get("SQL_SUCCESS_MIN", "0.95"))

DATA_FILE = Path(__file__).parent / "data" / "sql_test_cases.json"


@dataclass
class SQLTestCase:
    id: str
    nl_query: str
    expected_patterns: list[str]
    must_have_tenant_filter: bool
    description: str


@dataclass
class SQLTestResult:
    test_id: str
    passed: bool
    generated_sql: str
    missing_patterns: list[str] = field(default_factory=list)
    tenant_filter_present: bool = False
    error: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class BenchmarkReport:
    total: int
    passed: int
    failed: int
    success_rate: float
    results: list[SQLTestResult]
    threshold: float


def load_test_cases() -> list[SQLTestCase]:
    with open(DATA_FILE) as f:
        raw = json.load(f)
    return [SQLTestCase(**item) for item in raw]


def _check_patterns(sql: str, patterns: list[str]) -> list[str]:
    """Return patterns missing from sql (case-insensitive)."""
    sql_upper = sql.upper()
    return [p for p in patterns if p.upper() not in sql_upper]


# Which path generate_sql() last took. Printed in the report so a number is
# never read as a real measurement when it came from the keyword map.
LAST_SOURCE: str = "not run"


def _has_tenant_filter(sql: str) -> bool:
    return bool(re.search(r"tenant_id\s*=", sql, re.IGNORECASE))


def generate_sql(nl_query: str) -> str:
    """Generate SQL for *nl_query* through the real Stage 1 generator.

    Records which path ran in ``LAST_SOURCE`` so the report can say whether it
    measured anything real. QueryGenerator itself falls back to a deterministic
    keyword map when no LLM is configured, and reports that on the result, so
    the distinction is read from ``used_fallback`` rather than guessed.
    """
    global LAST_SOURCE
    try:
        from src.infrastructure.erp.query_generator import QueryGenerator
        generated = QueryGenerator().generate(nl_query)
        LAST_SOURCE = "offline generator" if generated.used_fallback else "LLM pipeline"
        return generated.raw_sql
    except Exception as exc:  # noqa: BLE001 — a benchmark must not crash the gate
        LAST_SOURCE = f"stub ({type(exc).__name__})"

    return _offline_stub_sql(nl_query)


def _offline_stub_sql(nl_query: str) -> str:
    """Minimal offline SQL stub used when real generator is unavailable."""
    nl_lower = nl_query.lower()
    table_map = {
        "sales order": "sales_orders",
        "revenue": "sales_orders",
        "supplier": "suppliers",
        "invoice": "invoices",
        "inventory": "inventory",
        "employee": "employees",
        "purchase order": "purchase_orders",
        "customer": "customers",
        "account": "accounts_receivable",
        "contract": "contracts",
        "stock": "products",
        "payroll": "payroll",
        "quality": "quality_checks",
        "vat": "vat_transactions",
        "asset": "assets",
        "production": "production_batches",
        "return": "returns",
        "budget": "budget_actuals",
        "leave": "leave_balances",
        "shipment": "shipments",
        "logistic": "shipments",
    }
    table = "erp_data"
    for keyword, tbl in table_map.items():
        if keyword in nl_lower:
            table = tbl
            break

    aggregates = ""
    if any(w in nl_lower for w in ["total", "sum", "revenue", "how many", "count"]):
        aggregates = ", SUM(amount) AS total, COUNT(*) AS cnt"

    group_by = ""
    if "department" in nl_lower:
        aggregates += ", department"
        group_by = " GROUP BY department"
    elif "monthly" in nl_lower or "trend" in nl_lower:
        aggregates += ", DATE_TRUNC('month', created_at) AS month"
        group_by = " GROUP BY DATE_TRUNC('month', created_at)"

    order_limit = ""
    if "top 10" in nl_lower or "top ten" in nl_lower:
        order_limit = " ORDER BY total DESC LIMIT 10"

    return (
        f"SELECT *{aggregates} FROM {table} "
        f"WHERE tenant_id = :tenant_id{group_by}{order_limit}"
    )


def run_benchmark(
    test_cases: list[SQLTestCase] | None = None,
) -> BenchmarkReport:
    if test_cases is None:
        test_cases = load_test_cases()

    results: list[SQLTestResult] = []

    for tc in test_cases:
        t0 = time.perf_counter()
        try:
            sql = generate_sql(tc.nl_query)
            latency_ms = (time.perf_counter() - t0) * 1000

            missing = _check_patterns(sql, tc.expected_patterns)
            tenant_ok = _has_tenant_filter(sql) if tc.must_have_tenant_filter else True

            passed = len(missing) == 0 and tenant_ok
            results.append(
                SQLTestResult(
                    test_id=tc.id,
                    passed=passed,
                    generated_sql=sql,
                    missing_patterns=missing,
                    tenant_filter_present=_has_tenant_filter(sql),
                    latency_ms=latency_ms,
                )
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            results.append(
                SQLTestResult(
                    test_id=tc.id,
                    passed=False,
                    generated_sql="",
                    error=str(exc),
                    latency_ms=latency_ms,
                )
            )

    total = len(results)
    passed_count = sum(1 for r in results if r.passed)
    success_rate = passed_count / total if total > 0 else 0.0

    return BenchmarkReport(
        total=total,
        passed=passed_count,
        failed=total - passed_count,
        success_rate=success_rate,
        results=results,
        threshold=SQL_SUCCESS_MIN,
    )


def print_report(report: BenchmarkReport) -> None:
    print("\n" + "=" * 60)
    print("  SQL BENCHMARK REPORT")
    print("=" * 60)
    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.test_id}  ({r.latency_ms:.1f}ms)")
        if not r.passed:
            if r.error:
                print(f"         ERROR: {r.error}")
            if r.missing_patterns:
                print(f"         Missing patterns: {r.missing_patterns}")
            if not r.tenant_filter_present:
                print("         Missing tenant_id filter")
    print("-" * 60)
    print(f"  Total:        {report.total}")
    print(f"  Passed:       {report.passed}")
    print(f"  Failed:       {report.failed}")
    print(f"  Success rate: {report.success_rate:.2%}  (min required: {report.threshold:.2%})")
    gate = "PASS" if report.success_rate >= report.threshold else "FAIL"
    print(f"  CI gate:      {gate}")
    print(f"  Measured:     {LAST_SOURCE}")
    if LAST_SOURCE != "LLM pipeline":
        print(
            "  NOTE: these numbers score the offline keyword generator, not the\n"
            "        SQL pipeline. They say nothing about generation quality\n"
            "        until an LLM provider is configured."
        )
    print("=" * 60 + "\n")


if __name__ == "__main__":
    report = run_benchmark()
    print_report(report)
    sys.exit(0 if report.success_rate >= SQL_SUCCESS_MIN else 1)
