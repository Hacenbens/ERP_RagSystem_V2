"""
LLM-backed SQL generation — Sprint 12 (S12·2).

The offline generator matches the first keyword it recognises and stops, so it
does not know the schema and writes confident SQL against the wrong table:

    "overdue invoices by supplier"
    -> SELECT * FROM suppliers WHERE ... due_date < CURRENT_DATE
       (matched "supplier"; the invoice aggregate is gone)

The LLM path picks the right table. Given only table names it then invents
plausible columns — ``quantity_on_hand``, ``warehouse_location`` — and the
query dies with ``column "name" does not exist``, so ErpSchemaProvider hands it
the real schema.

Rejection is deliberately strict. Every check below turns a bad generation into
deterministic SQL that answers the question, rather than a validation error the
user sees or, worse, a statement that quietly reads the wrong tenant.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest

from src.domain.ports.llm_port import LLMPort
from src.infrastructure.erp.query_generator import ALLOWED_TABLES, QueryGenerator
from src.infrastructure.erp.schema_provider import ErpSchemaProvider
from src.prompts.registry import PromptRegistry

PROMPTS = PromptRegistry("src/prompts")
TEST_DSN = os.environ.get("ERP_PG_TEST_DSN", "")

GOOD_SQL = "SELECT SUM(amount) AS total FROM invoices WHERE tenant_id = :tenant_id"


def _llm(reply: str) -> MagicMock:
    m = MagicMock(spec=LLMPort)
    m.complete.return_value = reply
    return m


def _gen(reply: str, schema: ErpSchemaProvider | None = None) -> QueryGenerator:
    return QueryGenerator(llm=_llm(reply), registry=PROMPTS, schema=schema)


class TestResponseShapes:
    """Models return the SQL in whatever shape they feel like."""

    def test_plain_json_object(self):
        result = _gen(json.dumps({"sql": GOOD_SQL})).generate("total invoiced")

        assert result.raw_sql == GOOD_SQL
        assert result.used_fallback is False

    def test_json_wrapped_in_a_markdown_fence(self):
        """Gemini fences everything; this is the common case, not the edge."""
        reply = f"```json\n{json.dumps({'sql': GOOD_SQL})}\n```"

        assert _gen(reply).generate("total invoiced").raw_sql == GOOD_SQL

    def test_a_bare_select_is_accepted(self):
        """Ignoring the JSON instruction is not a reason to discard usable SQL."""
        assert _gen(GOOD_SQL).generate("total invoiced").raw_sql == GOOD_SQL

    def test_a_trailing_semicolon_is_stripped(self):
        assert _gen(json.dumps({"sql": GOOD_SQL + ";"})).generate("q").raw_sql == GOOD_SQL


class TestUnsafeGenerationsFallBack:
    """Each of these produces deterministic SQL instead of a bad answer."""

    @pytest.mark.parametrize(
        "reply, why",
        [
            (json.dumps({"sql": "DELETE FROM invoices WHERE tenant_id = :tenant_id"}),
             "not a SELECT"),
            (json.dumps({"sql": "SELECT * FROM invoices WHERE tenant_id = 'acme'"}),
             "literal tenant — would read another tenant's rows"),
            (json.dumps({"sql": "SELECT * FROM invoices"}),
             "no tenant filter at all"),
            (json.dumps({"sql": "SELECT * FROM salaries WHERE tenant_id = :tenant_id"}),
             "table outside the allowed set"),
            (json.dumps({"nope": "wrong key"}), "no sql key"),
            ("I cannot help with that.", "not SQL at all"),
            ("", "empty response"),
        ],
        ids=["delete", "literal-tenant", "no-tenant", "unknown-table",
             "no-sql-key", "prose", "empty"],
    )
    def test_bad_generation_falls_back_to_offline(self, reply, why):
        result = _gen(reply).generate("total revenue from sales orders")

        assert result.used_fallback is True, why
        assert result.model == "offline"
        assert ":tenant_id" in result.raw_sql

    def test_the_literal_tenant_case_is_the_one_that_matters(self):
        """A hardcoded tenant is a cross-tenant read, not a formatting slip.

        The prompt used to instruct exactly this, so the generator refuses it
        rather than trusting Stage 2 to be the only line of defence.
        """
        reply = json.dumps({"sql": "SELECT * FROM invoices WHERE tenant_id = 'acme'"})

        assert "'acme'" not in _gen(reply).generate("q").raw_sql


class TestPromptContents:
    def test_the_model_is_told_the_allowed_tables(self):
        gen = _gen(json.dumps({"sql": GOOD_SQL}))
        gen.generate("total invoiced")

        prompt = gen._llm.complete.call_args[0][0]  # type: ignore[attr-defined]
        for table in ("invoices", "sales_orders", "employees"):
            assert table in prompt

    def test_the_tenant_is_context_not_interpolated_into_sql(self):
        gen = _gen(json.dumps({"sql": GOOD_SQL}))
        result = gen.generate("total invoiced", tenant_id="ferza")

        assert "ferza" not in result.raw_sql
        assert ":tenant_id" in result.raw_sql

    def test_schema_columns_reach_the_prompt_when_available(self):
        class _FakeSchema(ErpSchemaProvider):
            def __init__(self) -> None:
                super().__init__("", ALLOWED_TABLES)

            def describe(self) -> str:
                return "  invoices(id int, amount numeric, due_date date)"

        gen = _gen(json.dumps({"sql": GOOD_SQL}), schema=_FakeSchema())
        gen.generate("total invoiced")

        prompt = gen._llm.complete.call_args[0][0]  # type: ignore[attr-defined]
        assert "amount numeric" in prompt


class TestOfflinePathUnchanged:
    """CI has no provider; the deterministic path must keep working."""

    def test_no_llm_means_offline(self):
        result = QueryGenerator().generate("total revenue from sales orders")

        assert result.used_fallback is True
        assert result.model == "offline"
        assert "tenant_id = :tenant_id" in result.raw_sql

    def test_registry_without_llm_is_still_offline(self):
        result = QueryGenerator(registry=PROMPTS).generate("total revenue")

        assert result.used_fallback is True

    def test_an_llm_that_raises_falls_back(self):
        llm = MagicMock(spec=LLMPort)
        llm.complete.side_effect = ConnectionError("provider down")

        result = QueryGenerator(llm=llm, registry=PROMPTS).generate("total revenue")

        assert result.used_fallback is True
        assert ":tenant_id" in result.raw_sql


class TestSchemaProvider:
    def test_without_a_dsn_it_returns_table_names(self):
        described = ErpSchemaProvider("", ALLOWED_TABLES).describe()

        assert "invoices" in described
        assert "(" not in described  # names only, no column lists

    def test_an_unreachable_database_degrades_rather_than_raises(self):
        """A schema lookup failure must not take the query with it."""
        provider = ErpSchemaProvider(
            "postgresql://nobody:nope@127.0.0.1:1/none", ALLOWED_TABLES
        )

        assert "invoices" in provider.describe()

    @pytest.mark.skipif(not TEST_DSN, reason="ERP_PG_TEST_DSN not set")
    def test_it_describes_real_columns(self):
        described = ErpSchemaProvider(TEST_DSN, ALLOWED_TABLES).describe()

        assert "sales_orders(" in described
        assert "tenant_id text" in described
        assert "amount numeric" in described

    @pytest.mark.skipif(not TEST_DSN, reason="ERP_PG_TEST_DSN not set")
    def test_it_only_describes_allowed_tables(self):
        described = ErpSchemaProvider(TEST_DSN, ("invoices",)).describe()

        assert "invoices(" in described
        assert "sales_orders(" not in described

    @pytest.mark.skipif(not TEST_DSN, reason="ERP_PG_TEST_DSN not set")
    def test_introspection_happens_once(self):
        provider = ErpSchemaProvider(TEST_DSN, ALLOWED_TABLES)
        first = provider.describe()

        provider._dsn = "postgresql://broken"  # a second lookup would fail
        assert provider.describe() == first
