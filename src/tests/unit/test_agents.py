"""
Unit tests for BaseAgent, RAGAgent, SQLAgent — Sprint 7 Task 7.

Coverage categories per tester.md:
  1. Happy path
  2. Failure paths (≥2 per agent)
  3. Security-critical paths (SQLAgent tenant-filter gate)
  4. Edge cases (empty retrieval, empty rows, long query)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.agents.base_agent import AgentContext, BaseAgent
from src.agents.query_classifier_agent import QueryClassifierAgent
from src.agents.rag_agent import RAGAgent, _render_prompt
from src.agents.sql_agent import SQLAgent, SQLAgentError
from src.domain.erp_module import ErpModule
from src.domain.models.rag_result import RAGResult
from src.domain.models.routing_decision import RoutingDecision
from src.domain.models.scored_chunk import ScoredChunk
from src.domain.models.sql_result import SQLResult
from src.domain.ports.llm_port import LLMPort
from src.domain.query_intent import QueryIntent
from src.infrastructure.erp.query_executor import ExecutionResult
from src.infrastructure.erp.query_generator import GeneratedSQL
from src.infrastructure.erp.query_validator import ValidationReport
from src.prompts.registry import PromptRegistry

# ---------------------------------------------------------------------------
# Constants & shared fixtures
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

_CTX = AgentContext(tenant_id="t-acme", erp_module="finance", trace_id="tr-001")
_CTX_NO_MODULE = AgentContext(tenant_id="t-acme")

_VALID_SQL = "SELECT id FROM invoices WHERE tenant_id = :tenant_id LIMIT 10"

_VALID_RAG_JSON = json.dumps({
    "grounded": True,
    "answer": "VAT rate is 9% [c-1].",
    "cited_chunks": ["c-1"],
    "confidence": 0.91,
    "insufficient_data_for": [],
})

_UNGROUNDED_RAG_JSON = json.dumps({
    "grounded": False,
    "answer": None,
    "cited_chunks": [],
    "confidence": 0.0,
    "insufficient_data_for": ["VAT policy 2024"],
})


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

class _StubLLM(LLMPort):
    """Controllable LLM that returns a preset string."""

    def __init__(self, response: str = _VALID_RAG_JSON) -> None:
        self._response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        self.calls.append(prompt)
        return self._response


def _chunk(chunk_id: str = "c-1", score: float = 0.92) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        content="VAT rate is 9%.",
        score=score,
        source="tax-circular.pdf",
        erp_module="finance",
    )


def _mock_retriever(chunks: list[ScoredChunk]) -> MagicMock:
    m = MagicMock()
    m.retrieve.return_value = chunks
    return m


def _mock_reranker(chunks: list[ScoredChunk]) -> MagicMock:
    m = MagicMock()
    m.rerank.return_value = chunks
    return m


def _mock_context_builder(context_str: str = "some ERP context") -> MagicMock:
    m = MagicMock()
    m.build.return_value = context_str
    return m


def _make_valid_report(sql: str = _VALID_SQL) -> ValidationReport:
    return ValidationReport(
        raw_sql=sql,
        is_valid=True,
        has_tenant_filter=True,
        is_select_only=True,
        sanitized_sql=sql,
        errors=[],
        warnings=[],
    )


_DEFAULT_ROWS = [{"invoice_id": "inv-1"}]


def _make_execution(
    sql: str = _VALID_SQL,
    rows: list | None = None,
) -> ExecutionResult:
    actual_rows = _DEFAULT_ROWS if rows is None else rows
    return ExecutionResult(
        query_id="exec-42",
        sql=sql,
        tenant_id="t-acme",
        rows=actual_rows,
        row_count=len(actual_rows),
        latency_ms=42.0,
    )


def _make_sql_agent(
    raw_sql: str = _VALID_SQL,
    report: ValidationReport | None = None,
    execution: ExecutionResult | None = None,
) -> tuple[SQLAgent, MagicMock, MagicMock, MagicMock]:
    gen = MagicMock()
    gen.generate.return_value = GeneratedSQL(
        nl_query="any", raw_sql=raw_sql, latency_ms=5.0, model="offline"
    )
    val = MagicMock()
    val.validate.return_value = report or _make_valid_report(raw_sql)
    exe = MagicMock()
    exe.execute.return_value = execution or _make_execution(raw_sql)
    return SQLAgent(generator=gen, validator=val, executor=exe), gen, val, exe


# ---------------------------------------------------------------------------
# 1. BaseAgent contract
# ---------------------------------------------------------------------------

class TestBaseAgentContract:
    def test_base_agent_cannot_be_instantiated_directly(self) -> None:
        with pytest.raises(TypeError):
            BaseAgent()  # type: ignore[abstract]

    def test_subclass_without_run_cannot_be_instantiated(self) -> None:
        class _Incomplete(BaseAgent):
            pass

        with pytest.raises(TypeError):
            _Incomplete()  # type: ignore[abstract]

    def test_llm_port_cannot_be_instantiated_directly(self) -> None:
        with pytest.raises(TypeError):
            LLMPort()  # type: ignore[abstract]

    def test_concrete_subclass_satisfies_contract(self) -> None:
        class _ConcreteAgent(BaseAgent):
            async def run(self, query: str, context: AgentContext) -> RAGResult:
                return RAGResult.not_grounded()

        agent = _ConcreteAgent()
        assert isinstance(agent, BaseAgent)


# ---------------------------------------------------------------------------
# 2. AgentContext
# ---------------------------------------------------------------------------

class TestAgentContext:
    def test_agent_context_is_frozen(self) -> None:
        ctx = AgentContext(tenant_id="t-1")
        with pytest.raises((AttributeError, TypeError)):
            ctx.tenant_id = "other"  # type: ignore[misc]

    def test_agent_context_defaults(self) -> None:
        ctx = AgentContext(tenant_id="t-1")
        assert ctx.erp_module is None
        assert ctx.role == "analyst"
        assert ctx.trace_id == ""

    def test_agent_context_all_fields(self) -> None:
        ctx = AgentContext(
            tenant_id="t-1",
            erp_module="finance",
            role="admin",
            trace_id="tr-xyz",
        )
        assert ctx.tenant_id == "t-1"
        assert ctx.erp_module == "finance"
        assert ctx.role == "admin"
        assert ctx.trace_id == "tr-xyz"


# ---------------------------------------------------------------------------
# 3. _render_prompt helper
# ---------------------------------------------------------------------------

class TestRenderPrompt:
    def test_render_prompt_replaces_masked_query(self) -> None:
        text = "PREFIX\nUSER QUERY: {{masked_query}}\nSUFFIX"
        result = _render_prompt(text, "What is VAT?", "")
        assert "What is VAT?" in result
        assert "{{masked_query}}" not in result

    def test_render_prompt_replaces_each_block_with_context_str(self) -> None:
        text = "CHUNKS:\n{{#each chunks}}\n[{{id}}] {{content}}\n{{/each}}\nEND"
        result = _render_prompt(text, "q", "pre-built context")
        assert "pre-built context" in result
        assert "{{#each chunks}}" not in result
        assert "{{/each}}" not in result

    def test_render_prompt_with_empty_context_removes_block(self) -> None:
        text = "{{#each chunks}}\n{{content}}\n{{/each}}"
        result = _render_prompt(text, "q", "")
        assert "{{#each" not in result


# ---------------------------------------------------------------------------
# 4. RAGAgent — happy path
# ---------------------------------------------------------------------------

class TestRAGAgentHappyPath:
    @pytest.fixture()
    def registry(self) -> PromptRegistry:
        return PromptRegistry(PROMPTS_DIR)

    @pytest.mark.asyncio
    async def test_rag_agent_valid_input_returns_rag_result(
        self, registry: PromptRegistry
    ) -> None:
        llm = _StubLLM(_VALID_RAG_JSON)
        chunks = [_chunk()]
        agent = RAGAgent(
            retriever=_mock_retriever(chunks),
            reranker=_mock_reranker(chunks),
            context_builder=_mock_context_builder(),
            llm=llm,
            registry=registry,
        )

        result = await agent.run("What is the VAT rate?", _CTX)

        assert isinstance(result, RAGResult)
        assert result.grounded is True
        assert result.answer == "VAT rate is 9% [c-1]."
        assert result.confidence == 0.91
        assert "c-1" in result.cited_chunks

    @pytest.mark.asyncio
    async def test_rag_agent_passes_tenant_and_module_to_retriever(
        self, registry: PromptRegistry
    ) -> None:
        retriever = _mock_retriever([])
        agent = RAGAgent(
            retriever=retriever,
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(""),
            llm=_StubLLM(_VALID_RAG_JSON),
            registry=registry,
        )

        await agent.run("VAT query", _CTX)

        retriever.retrieve.assert_called_once_with(
            "VAT query",
            k=20,
            tenant_id="t-acme",
            erp_module="finance",
        )

    @pytest.mark.asyncio
    async def test_rag_agent_passes_none_erp_module_when_absent(
        self, registry: PromptRegistry
    ) -> None:
        retriever = _mock_retriever([])
        agent = RAGAgent(
            retriever=retriever,
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(""),
            llm=_StubLLM(_VALID_RAG_JSON),
            registry=registry,
        )

        await agent.run("query", _CTX_NO_MODULE)

        _, kwargs = retriever.retrieve.call_args
        assert kwargs.get("erp_module") is None

    @pytest.mark.asyncio
    async def test_rag_agent_respects_custom_retrieve_k(
        self, registry: PromptRegistry
    ) -> None:
        retriever = _mock_retriever([])
        agent = RAGAgent(
            retriever=retriever,
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(""),
            llm=_StubLLM(_VALID_RAG_JSON),
            registry=registry,
            retrieve_k=10,
        )

        await agent.run("query", _CTX)

        retriever.retrieve.assert_called_once()
        assert retriever.retrieve.call_args[1].get("k") == 10 or \
               retriever.retrieve.call_args[0][1] == 10

    @pytest.mark.asyncio
    async def test_rag_agent_respects_custom_rerank_top_k(
        self, registry: PromptRegistry
    ) -> None:
        chunks = [_chunk()]
        reranker = _mock_reranker(chunks)
        agent = RAGAgent(
            retriever=_mock_retriever(chunks),
            reranker=reranker,
            context_builder=_mock_context_builder(),
            llm=_StubLLM(_VALID_RAG_JSON),
            registry=registry,
            rerank_top_k=3,
        )

        await agent.run("query", _CTX)

        reranker.rerank.assert_called_once()
        call_args = reranker.rerank.call_args
        top_k = call_args[1].get("top_k") or call_args[0][2]
        assert top_k == 3

    @pytest.mark.asyncio
    async def test_rag_agent_returns_cited_chunks_as_tuple(
        self, registry: PromptRegistry
    ) -> None:
        result = await RAGAgent(
            retriever=_mock_retriever([]),
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(),
            llm=_StubLLM(_VALID_RAG_JSON),
            registry=registry,
        ).run("q", _CTX)

        assert isinstance(result.cited_chunks, tuple)

    @pytest.mark.asyncio
    async def test_rag_agent_ungrounded_llm_output_maps_correctly(
        self, registry: PromptRegistry
    ) -> None:
        result = await RAGAgent(
            retriever=_mock_retriever([]),
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(""),
            llm=_StubLLM(_UNGROUNDED_RAG_JSON),
            registry=registry,
        ).run("q", _CTX)

        assert result.grounded is False
        assert result.answer is None
        assert "VAT policy 2024" in result.insufficient_data_for


# ---------------------------------------------------------------------------
# 5. RAGAgent — failure / fallback paths
# ---------------------------------------------------------------------------

class TestRAGAgentFailurePaths:
    @pytest.fixture()
    def registry(self) -> PromptRegistry:
        return PromptRegistry(PROMPTS_DIR)

    @pytest.mark.asyncio
    async def test_rag_agent_invalid_json_falls_back_to_not_grounded(
        self, registry: PromptRegistry
    ) -> None:
        result = await RAGAgent(
            retriever=_mock_retriever([]),
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(),
            llm=_StubLLM("this is not JSON at all"),
            registry=registry,
        ).run("query", _CTX)

        assert result.grounded is False
        assert result.answer is None

    @pytest.mark.asyncio
    async def test_rag_agent_schema_violation_falls_back_to_not_grounded(
        self, registry: PromptRegistry
    ) -> None:
        bad = json.dumps({"grounded": "not-a-bool", "answer": 42})
        result = await RAGAgent(
            retriever=_mock_retriever([]),
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(),
            llm=_StubLLM(bad),
            registry=registry,
        ).run("query", _CTX)

        assert result.grounded is False

    @pytest.mark.asyncio
    async def test_rag_agent_empty_retrieval_still_calls_llm(
        self, registry: PromptRegistry
    ) -> None:
        llm = _StubLLM(_VALID_RAG_JSON)
        await RAGAgent(
            retriever=_mock_retriever([]),
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(""),
            llm=llm,
            registry=registry,
        ).run("query with no results", _CTX)

        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_rag_agent_llm_called_with_query_in_prompt(
        self, registry: PromptRegistry
    ) -> None:
        llm = _StubLLM(_VALID_RAG_JSON)
        await RAGAgent(
            retriever=_mock_retriever([]),
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(),
            llm=llm,
            registry=registry,
        ).run("unique query xyz", _CTX)

        assert "unique query xyz" in llm.calls[0]


# ---------------------------------------------------------------------------
# 6. SQLAgent — happy path
# ---------------------------------------------------------------------------

class TestSQLAgentHappyPath:
    @pytest.mark.asyncio
    async def test_sql_agent_valid_query_returns_sql_result(self) -> None:
        agent, _, _, _ = _make_sql_agent()
        result = await agent.run("List invoices", _CTX)

        assert isinstance(result, SQLResult)
        assert result.row_count == 1
        assert result.query_id == "exec-42"
        assert isinstance(result.rows, tuple)

    @pytest.mark.asyncio
    async def test_sql_agent_passes_query_and_tenant_to_generator(self) -> None:
        agent, gen, _, _ = _make_sql_agent()
        await agent.run("List invoices", _CTX)

        gen.generate.assert_called_once_with(nl_query="List invoices", tenant_id="t-acme")

    @pytest.mark.asyncio
    async def test_sql_agent_passes_report_and_tenant_to_executor(self) -> None:
        agent, _, _, exe = _make_sql_agent()
        await agent.run("List invoices", _CTX)

        exe.execute.assert_called_once()
        call_args = exe.execute.call_args
        tenant_arg = call_args[1].get("tenant_id") or call_args[0][1]
        assert tenant_arg == "t-acme"

    @pytest.mark.asyncio
    async def test_sql_agent_maps_execution_result_to_sql_result_fields(self) -> None:
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        agent, _, _, _ = _make_sql_agent(execution=_make_execution(rows=rows))
        result = await agent.run("list three rows", _CTX)

        assert result.row_count == 3
        assert len(result.rows) == 3
        assert result.latency_ms == 42.0

    @pytest.mark.asyncio
    async def test_sql_agent_empty_result_set_is_valid(self) -> None:
        agent, _, _, _ = _make_sql_agent(execution=_make_execution(rows=[]))
        result = await agent.run("no data query", _CTX)

        assert result.row_count == 0
        assert result.rows == ()


# ---------------------------------------------------------------------------
# 7. SQLAgent — security & validation failure paths
# ---------------------------------------------------------------------------

class TestSQLAgentSecurityPaths:
    """Security-critical: SQLAgent must never execute SQL with missing tenant filter."""

    @pytest.mark.asyncio
    async def test_sql_agent_missing_tenant_filter_raises_sql_agent_error(self) -> None:
        bad_sql = "SELECT * FROM invoices"  # no WHERE tenant_id
        gen = MagicMock()
        gen.generate.return_value = GeneratedSQL(
            nl_query="x", raw_sql=bad_sql, latency_ms=1.0, model="offline"
        )
        val = MagicMock()
        val.validate.return_value = ValidationReport(
            raw_sql=bad_sql,
            is_valid=False,
            has_tenant_filter=False,
            is_select_only=True,
            sanitized_sql=bad_sql,
            errors=["Missing tenant_id filter."],
            warnings=[],
        )
        exe = MagicMock()
        agent = SQLAgent(generator=gen, validator=val, executor=exe)

        with pytest.raises(SQLAgentError, match="has_tenant_filter=False"):
            await agent.run("list invoices no tenant", _CTX)

        exe.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_sql_agent_write_statement_raises_sql_agent_error(self) -> None:
        bad_sql = "DROP TABLE invoices"
        gen = MagicMock()
        gen.generate.return_value = GeneratedSQL(
            nl_query="x", raw_sql=bad_sql, latency_ms=1.0, model="offline"
        )
        val = MagicMock()
        val.validate.return_value = ValidationReport(
            raw_sql=bad_sql,
            is_valid=False,
            has_tenant_filter=False,
            is_select_only=False,
            sanitized_sql=bad_sql,
            errors=["Only SELECT statements are permitted.", "Forbidden SQL keyword: DROP"],
            warnings=[],
        )
        exe = MagicMock()
        agent = SQLAgent(generator=gen, validator=val, executor=exe)

        with pytest.raises(SQLAgentError):
            await agent.run("drop all tables", _CTX)

        exe.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_sql_agent_does_not_swallow_validation_errors(self) -> None:
        gen = MagicMock()
        gen.generate.return_value = GeneratedSQL(
            nl_query="x", raw_sql="bad", latency_ms=1.0, model="offline"
        )
        val = MagicMock()
        val.validate.return_value = ValidationReport(
            raw_sql="bad",
            is_valid=False,
            has_tenant_filter=False,
            is_select_only=False,
            sanitized_sql="bad",
            errors=["many errors"],
            warnings=[],
        )
        agent = SQLAgent(generator=gen, validator=val, executor=MagicMock())

        with pytest.raises(SQLAgentError):
            await agent.run("bad query", _CTX)

    @pytest.mark.asyncio
    async def test_sql_agent_uses_real_query_validator_blocks_injection(self) -> None:
        """End-to-end: real QueryValidator correctly blocks a UNION injection."""
        from src.infrastructure.erp.query_validator import QueryValidator

        injection_sql = "SELECT * FROM invoices UNION SELECT * FROM users"
        gen = MagicMock()
        gen.generate.return_value = GeneratedSQL(
            nl_query="x", raw_sql=injection_sql, latency_ms=1.0, model="offline"
        )
        agent = SQLAgent(
            generator=gen,
            validator=QueryValidator(),
            executor=MagicMock(),
        )

        with pytest.raises(SQLAgentError):
            await agent.run("union injection", _CTX)


# ---------------------------------------------------------------------------
# 8. Edge cases
# ---------------------------------------------------------------------------

class TestAgentEdgeCases:
    @pytest.fixture()
    def registry(self) -> PromptRegistry:
        return PromptRegistry(PROMPTS_DIR)

    @pytest.mark.asyncio
    async def test_rag_agent_long_query_does_not_crash(
        self, registry: PromptRegistry
    ) -> None:
        long_query = "what is the VAT rate " * 200
        result = await RAGAgent(
            retriever=_mock_retriever([]),
            reranker=_mock_reranker([]),
            context_builder=_mock_context_builder(""),
            llm=_StubLLM(_VALID_RAG_JSON),
            registry=registry,
        ).run(long_query, _CTX)

        assert isinstance(result, RAGResult)

    @pytest.mark.asyncio
    async def test_sql_agent_long_query_does_not_crash(self) -> None:
        long_query = "list all invoices " * 100
        agent, _, _, _ = _make_sql_agent()
        result = await agent.run(long_query, _CTX)

        assert isinstance(result, SQLResult)


# ---------------------------------------------------------------------------
# TestQueryClassifierAgent — Sprint 8 Task 7C
# ---------------------------------------------------------------------------

def _make_classifier(llm_answer: str) -> QueryClassifierAgent:
    mock_llm = MagicMock(spec=LLMPort)
    mock_llm.complete.return_value = llm_answer
    registry = PromptRegistry(PROMPTS_DIR)
    return QueryClassifierAgent(llm=mock_llm, registry=registry)


class TestQueryClassifierAgent:
    def test_classifier_agent_returns_rag_intent_for_policy_query(self):
        payload = json.dumps({"intent": "RAG", "confidence": 0.92, "reason": "policy lookup"})
        agent = _make_classifier(payload)
        decision = agent.classify("What is the VAT rate for exported goods?")
        assert decision.intent == QueryIntent.RAG

    def test_classifier_agent_returns_sql_intent_for_data_query(self):
        payload = json.dumps({"intent": "SQL", "confidence": 0.88, "reason": "structured data"})
        agent = _make_classifier(payload)
        decision = agent.classify("Show all unpaid invoices over 90 days.")
        assert decision.intent == QueryIntent.SQL

    def test_classifier_agent_returns_hybrid_intent_for_combined_query(self):
        payload = json.dumps({"intent": "HYBRID", "confidence": 0.75, "reason": "needs both"})
        agent = _make_classifier(payload)
        decision = agent.classify("What is our procurement policy and how many POs exceeded it?")
        assert decision.intent == QueryIntent.HYBRID

    def test_classifier_agent_returns_blocked_for_harmful_query(self):
        payload = json.dumps({"intent": "BLOCKED", "confidence": 0.99, "reason": "injection attempt"})
        agent = _make_classifier(payload)
        decision = agent.classify("Drop the users table.")
        assert decision.intent == QueryIntent.BLOCKED

    def test_classifier_agent_parses_confidence_field(self):
        payload = json.dumps({"intent": "RAG", "confidence": 0.77, "reason": "doc lookup"})
        agent = _make_classifier(payload)
        decision = agent.classify("Explain leave policy.")
        assert decision.confidence == pytest.approx(0.77)

    def test_classifier_agent_maps_erp_module_string_to_enum(self):
        payload = json.dumps({"intent": "SQL", "confidence": 0.90, "reason": "finance data"})
        agent = _make_classifier(payload)
        decision = agent.classify("Total invoices this month.", erp_module="finance")
        assert decision.erp_module == ErpModule.FINANCE

    def test_classifier_agent_unknown_erp_module_maps_to_none(self):
        payload = json.dumps({"intent": "RAG", "confidence": 0.80, "reason": "doc"})
        agent = _make_classifier(payload)
        decision = agent.classify("Some query.", erp_module="nonexistent_module")
        assert decision.erp_module is None

    def test_classifier_agent_none_erp_module_maps_to_none(self):
        payload = json.dumps({"intent": "RAG", "confidence": 0.85, "reason": "doc"})
        agent = _make_classifier(payload)
        decision = agent.classify("Some query.", erp_module=None)
        assert decision.erp_module is None

    def test_classifier_agent_raises_value_error_on_invalid_json(self):
        agent = _make_classifier("not json at all")
        with pytest.raises(ValueError, match="No JSON object"):
            agent.classify("Some query.")

    def test_classifier_agent_accepts_json_wrapped_in_a_markdown_fence(self):
        """Gemini fences its JSON, which a bare json.loads cannot read.

        Every agent called json.loads directly, so a fenced reply failed with
        "Expecting value: line 1 column 1 (char 0)" — and RAGAgent turned that
        into not_grounded(), indistinguishable from the model honestly saying
        it could not answer.
        """
        payload = json.dumps({"intent": "RAG", "confidence": 0.9, "reason": "doc"})
        agent = _make_classifier(f"```json\n{payload}\n```")

        assert agent.classify("Some query.").intent is QueryIntent.RAG

    def test_classifier_agent_raises_on_an_empty_response(self):
        agent = _make_classifier("")
        with pytest.raises(ValueError, match="empty"):
            agent.classify("Some query.")

    def test_classifier_agent_raises_value_error_on_schema_violation(self):
        bad_payload = json.dumps({"intent": "UNKNOWN_INTENT", "confidence": 0.5, "reason": "x"})
        agent = _make_classifier(bad_payload)
        with pytest.raises(ValueError, match="schema validation"):
            agent.classify("Some query.")

    def test_classifier_agent_returns_routing_decision_instance(self):
        payload = json.dumps({"intent": "RAG", "confidence": 0.90, "reason": "test"})
        agent = _make_classifier(payload)
        result = agent.classify("Any query.")
        assert isinstance(result, RoutingDecision)

    def test_classifier_agent_implements_query_classifier_port(self):
        from src.domain.ports.query_classifier_port import QueryClassifierPort
        mock_llm = MagicMock(spec=LLMPort)
        mock_llm.complete.return_value = json.dumps(
            {"intent": "RAG", "confidence": 0.9, "reason": "ok"}
        )
        agent = QueryClassifierAgent(llm=mock_llm, registry=PromptRegistry(PROMPTS_DIR))
        assert isinstance(agent, QueryClassifierPort)
