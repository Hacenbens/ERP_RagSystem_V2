"""
SQL Pipeline — Stage 1: Query Generator
NL query → raw SQL string

Architecture rule: this stage only generates SQL.
It does NOT validate or execute — that is Stage 2 and Stage 3.

Real implementation calls LLM (OpenAI/vLLM).
Offline fallback generates deterministic SQL from keyword mapping
(used when OPENAI_API_KEY is absent or in unit tests).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from src.observability.prometheus_metrics import SQL_STAGE1_LATENCY
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class GeneratedSQL:
    """Output of Stage 1."""
    nl_query: str
    raw_sql: str
    latency_ms: float
    model: str
    used_fallback: bool = False


# ---------------------------------------------------------------------------
# Keyword → table mapping (shared with offline fallback)
# ---------------------------------------------------------------------------

_TABLE_MAP: dict[str, str] = {
    "sales order": "sales_orders",
    "revenue": "sales_orders",
    "supplier": "suppliers",
    "invoice": "invoices",
    "inventory": "inventory",
    "stock": "products",
    "employee": "employees",
    "leave": "leave_balances",
    "payroll": "payroll",
    "purchase order": "purchase_orders",
    "customer": "customers",
    "account receivable": "accounts_receivable",
    "contract": "contracts",
    "asset": "assets",
    "depreciation": "assets",
    "production": "production_batches",
    "quality": "quality_checks",
    "vat": "vat_transactions",
    "tax": "vat_transactions",
    "budget": "budget_actuals",
    "shipment": "shipments",
    "logistics": "shipments",
    "return": "returns",
    "refund": "returns",
}


def _offline_generate(nl_query: str) -> str:
    """Deterministic offline SQL generation — no LLM call."""
    q = nl_query.lower()

    table = "erp_records"
    for keyword, tbl in _TABLE_MAP.items():
        if keyword in q:
            table = tbl
            break

    select_cols = "*"
    aggregates = []
    group_by = ""
    order_limit = ""
    where_extras = []

    if any(w in q for w in ["total", "sum", "revenue"]):
        aggregates.append("SUM(amount) AS total_amount")
    if any(w in q for w in ["count", "how many", "number of"]):
        aggregates.append("COUNT(*) AS record_count")
    if "department" in q:
        aggregates.append("department")
        group_by = " GROUP BY department"
    if any(w in q for w in ["monthly", "trend", "per month"]):
        aggregates.append("DATE_TRUNC('month', created_at) AS month")
        group_by = " GROUP BY DATE_TRUNC('month', created_at)"
    if "top 10" in q or "top ten" in q:
        order_limit = " ORDER BY total_amount DESC LIMIT 10"
    if "overdue" in q or "past due" in q:
        where_extras.append("due_date < CURRENT_DATE")
    if "pending" in q or "open" in q:
        where_extras.append("status = 'pending'")
    if "active" in q:
        where_extras.append("status = 'active'")
    if "last 30 days" in q or "past 30 days" in q:
        where_extras.append("created_at >= CURRENT_DATE - INTERVAL '30 days'")
    if "last 6 months" in q:
        where_extras.append("created_at >= CURRENT_DATE - INTERVAL '6 months'")

    if aggregates:
        select_cols = ", ".join(aggregates)

    where_clause = "tenant_id = :tenant_id"
    if where_extras:
        where_clause += " AND " + " AND ".join(where_extras)

    return (
        f"SELECT {select_cols} FROM {table} "
        f"WHERE {where_clause}{group_by}{order_limit}"
    )


class QueryGenerator:
    """Stage 1 — generates raw SQL from a natural language query.

    Uses LLM when OPENAI_API_KEY is set; falls back to deterministic offline
    stub when the key is absent (CI / test environments).
    """

    def __init__(self, model: str = "gpt-4o") -> None:
        self._model = model
        self._api_key = os.environ.get("OPENAI_API_KEY", "")

    def generate(self, nl_query: str, tenant_id: str = ":tenant_id") -> GeneratedSQL:
        """Generate SQL for a natural-language query.

        Always parameterises the tenant with :tenant_id placeholder.
        The actual tenant_id is bound at Stage 3 execution time.
        """
        t0 = time.perf_counter()

        if self._api_key and self._api_key != "sk-...":
            sql = self._llm_generate(nl_query)
            used_fallback = False
        else:
            sql = _offline_generate(nl_query)
            used_fallback = True

        latency_ms = (time.perf_counter() - t0) * 1000
        SQL_STAGE1_LATENCY.observe(latency_ms / 1000)
        logger.info(
            "sql.stage1.generated",
            used_fallback=used_fallback,
            latency_ms=round(latency_ms, 2),
        )
        return GeneratedSQL(
            nl_query=nl_query,
            raw_sql=sql,
            latency_ms=latency_ms,
            model=self._model if not used_fallback else "offline",
            used_fallback=used_fallback,
        )

    def _llm_generate(self, nl_query: str) -> str:
        """Call OpenAI to generate SQL. Sprint 4 stub — real prompt in Sprint 7."""
        try:
            import openai  # type: ignore
            client = openai.OpenAI(api_key=self._api_key)
            prompt = (
                "You are an ERP SQL expert. Generate a single PostgreSQL SELECT "
                "statement for the following request. Always include "
                "WHERE tenant_id = :tenant_id. Output ONLY the SQL.\n\n"
                f"Request: {nl_query}"
            )
            response = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning("sql.stage1.llm_fallback", reason=str(exc))
            return _offline_generate(nl_query)


__all__ = ["QueryGenerator", "GeneratedSQL"]
