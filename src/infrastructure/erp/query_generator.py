"""
SQL Pipeline — Stage 1: Query Generator
NL query → raw SQL string

Architecture rule: this stage only generates SQL.
It does NOT validate or execute — that is Stage 2 and Stage 3.

Generation calls the injected LLMPort with the versioned ``sql_generator``
prompt. Without one — CI, tests, any environment with no provider — it falls
back to a deterministic keyword map.

The fallback is not a substitute. It matches the first keyword it recognises
and stops, so it does not know the schema and writes confident SQL against the
wrong table:

    "overdue invoices by supplier" -> SELECT * FROM suppliers WHERE ...
                                      (matched "supplier"; the invoice
                                       aggregate is gone)

Which is why every result records ``used_fallback``, and the caller surfaces it.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from src.domain.ports.llm_port import LLMPort
from src.infrastructure.generation.llm_json import parse_llm_json
from src.observability.prometheus_metrics import SQL_PIPELINE_ERRORS, SQL_STAGE1_LATENCY
from src.observability.structured_logger import get_logger
from src.infrastructure.erp.schema_provider import ErpSchemaProvider
from src.prompts.registry import PromptRegistry

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


# The tables the generator may reference, handed to the model in the prompt.
# Derived from _TABLE_MAP so the two cannot drift: a table the offline path can
# produce but the prompt does not list would be rejected downstream.
ALLOWED_TABLES: tuple[str, ...] = tuple(sorted(set(_TABLE_MAP.values())))

# Stage 3 binds the tenant. SQL carrying a literal ignores that binding and
# returns another tenant's rows, so a generated statement that does not use the
# bound parameter is discarded rather than repaired — a wrong tenant filter is
# not something to guess at.
_BOUND_TENANT_RE = re.compile(r"tenant_id\s*=\s*[:$]tenant_id", re.IGNORECASE)


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

    Args:
        llm:      any LLMPort — GeminiLLMClient, vLLMLLMClient, ModelSelector,
                  or the degraded-mode wrapper. ``None`` selects the offline
                  path, which is what CI and the unit tests run on.
        registry: PromptRegistry holding the versioned ``sql_generator`` prompt.
                  Both must be present for the LLM path to be used.
        schema:   describes the real tables and columns. Without it the model
                  is given table names alone and invents plausible columns —
                  "SELECT ... quantity_on_hand FROM inventory" against a schema
                  that has no such column.
    """

    def __init__(
        self,
        llm: LLMPort | None = None,
        registry: PromptRegistry | None = None,
        schema: "ErpSchemaProvider | None" = None,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._schema = schema

    def generate(
        self,
        nl_query: str,
        tenant_id: str = ":tenant_id",
        erp_module: str | None = None,
    ) -> GeneratedSQL:
        """Generate SQL for *nl_query*.

        The tenant is always the bound ``:tenant_id`` parameter, filled by
        Stage 3 from the caller's claims. ``tenant_id`` here is passed to the
        model as context only — never interpolated into the statement.
        """
        t0 = time.perf_counter()
        sql: str | None = None
        model_name = "offline"

        if self._llm is not None and self._registry is not None:
            try:
                sql, model_name = self._llm_generate(nl_query, tenant_id, erp_module)
            except Exception as exc:
                SQL_PIPELINE_ERRORS.labels(stage="stage1").inc()
                logger.warning(
                    "sql.stage1.llm_fallback",
                    error_type=type(exc).__name__,
                    reason=str(exc)[:200],
                )

        used_fallback = sql is None
        if sql is None:
            sql = _offline_generate(nl_query)
            model_name = "offline"

        latency_ms = (time.perf_counter() - t0) * 1000
        SQL_STAGE1_LATENCY.observe(latency_ms / 1000)
        logger.info(
            "sql.stage1.generated",
            used_fallback=used_fallback,
            model=model_name,
            latency_ms=round(latency_ms, 2),
        )
        return GeneratedSQL(
            nl_query=nl_query,
            raw_sql=sql,
            latency_ms=latency_ms,
            model=model_name,
            used_fallback=used_fallback,
        )

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _llm_generate(
        self, nl_query: str, tenant_id: str, erp_module: str | None
    ) -> tuple[str, str]:
        """Return ``(sql, model_name)`` from the LLM, or raise.

        Raises rather than falling back internally so ``generate`` owns the
        single fallback decision and records it once. Every rejection below is
        a reason to prefer deterministic SQL over a plausible-looking guess.
        """
        assert self._registry is not None and self._llm is not None  # generate() checks
        pv = self._registry.resolve("sql_generator", "production")
        prompt = self._build_prompt(
            pv.prompt_text, nl_query, tenant_id, erp_module, self._describe_schema()
        )

        raw = self._llm.complete(
            prompt,
            temperature=pv.parameters.temperature,
            max_tokens=pv.parameters.max_tokens,
        )
        sql = self._extract_sql(raw)
        self._reject_unsafe(sql)
        return sql, pv.parameters.model

    def _describe_schema(self) -> str:
        """Real tables and columns when available, bare table names otherwise."""
        if self._schema is not None:
            return self._schema.describe()
        return ", ".join(ALLOWED_TABLES)

    @staticmethod
    def _build_prompt(
        template: str,
        question: str,
        tenant_id: str,
        erp_module: str | None,
        schema: str,
    ) -> str:
        """Fill the prompt's placeholders."""
        return (
            template
            .replace("{{question}}", question)
            .replace("{{masked_query}}", question)
            .replace("{{tenant_id}}", tenant_id)
            .replace("{{erp_module}}", erp_module or "not specified")
            .replace("{{allowed_tables}}", schema)
        )

    @staticmethod
    def _extract_sql(raw: str) -> str:
        """Pull the SQL out of the model's reply.

        The prompt asks for a JSON object with a ``sql`` key. Models fence it,
        wrap it in prose, or ignore the instruction and return the bare
        statement — parse_llm_json handles the first two, and a bare SELECT is
        accepted as the last resort rather than discarding a usable answer over
        formatting.
        """
        try:
            payload = parse_llm_json(raw)
        except ValueError:
            cleaned = raw.strip().strip("`").strip()
            if re.match(r"^\s*SELECT\b", cleaned, re.IGNORECASE):
                return cleaned.rstrip(";").strip()
            raise

        sql = str(payload.get("sql") or "").strip()
        if not sql:
            raise ValueError(f"LLM response has no 'sql' key: {raw[:200]!r}")
        return sql.rstrip(";").strip()

    @staticmethod
    def _reject_unsafe(sql: str) -> None:
        """Discard SQL that Stage 2 would reject, or that leaks across tenants.

        Stage 2 validates independently and is the real gate; catching it here
        means a bad generation becomes deterministic SQL that answers the
        question, instead of a validation error the user sees.
        """
        if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
            raise ValueError(f"Generated SQL is not a SELECT: {sql[:120]!r}")

        if not _BOUND_TENANT_RE.search(sql):
            # Most often the model wrote tenant_id = 'ferza'. That ignores the
            # Stage 3 binding and would return whichever tenant it chose.
            raise ValueError(
                f"Generated SQL does not filter on the bound :tenant_id: {sql[:120]!r}"
            )

        referenced = set(re.findall(r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.IGNORECASE))
        referenced |= set(re.findall(r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.IGNORECASE))
        unknown = {t for t in referenced if t.lower() not in ALLOWED_TABLES}
        if unknown:
            raise ValueError(f"Generated SQL references unknown tables: {sorted(unknown)}")


__all__ = ["QueryGenerator", "GeneratedSQL"]
