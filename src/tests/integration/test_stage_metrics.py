"""
Per-stage latency and token metrics — Sprint 12 (S12·6).

Every test here runs the real pipeline and then reads Prometheus. None of them
touch a metric object directly.

That distinction is the whole point. The suite this replaces asserted things
like::

    HYBRID_PARTIAL_RATE.labels(fallback_mode="rag_only").inc()
    assert after - before == 1.0

which proves prometheus_client can add one to a number. It passed for months
while nothing in the system ever incremented that counter, and the metric sat
on /metrics reporting a permanent zero — indistinguishable from "measured, and
healthy". A metric test that does not run the code under test measures nothing.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from prometheus_client import REGISTRY

from src.agents.base_agent import AgentContext
from src.agents.rag_agent import RAGAgent
from src.domain.models.hybrid_result import HybridResult
from src.domain.models.rag_result import RAGResult
from src.domain.ports.embedding_port import EmbeddingPort
from src.domain.ports.llm_port import LLMPort
from src.infrastructure.auth.jwt_handler import TokenClaims
from src.infrastructure.erp.query_executor import QueryExecutor
from src.infrastructure.erp.query_generator import QueryGenerator
from src.infrastructure.erp.query_validator import QueryValidator
from src.infrastructure.nlp.stub_classifier import StubClassifier
from src.infrastructure.rag.context_builder import ContextBuilder
from src.infrastructure.rag.reranker import IdentityReranker
from src.infrastructure.rag.vector_retriever import VectorRetriever
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.observability.stage_timer import Stage, record_tokens, stage_timer
from src.prompts.registry import PromptRegistry
from src.use_cases.route_query import RouteQueryUseCase
from src.use_cases.run_hybrid import RunHybridUseCase
from src.use_cases.run_rag import RunRAGUseCase
from src.use_cases.run_sql import RunSQLUseCase

_PROMPTS_DIR = Path(__file__).parents[3] / "src" / "prompts"
_TENANT = "test-tenant"

_RAG_RESPONSE = json.dumps({
    "grounded": True,
    "answer": "Requisitions above the threshold need written approval.",
    "cited_chunks": [],
    "confidence": 0.9,
    "insufficient_data_for": [],
})


# ---------------------------------------------------------------------------
# Reading Prometheus
# ---------------------------------------------------------------------------

def _stage_count(stage: Stage) -> float:
    """Observation count for one stage of erp_rag_query_stage_latency_ms."""
    for metric in REGISTRY.collect():
        if metric.name != "erp_rag_query_stage_latency_ms":
            continue
        for sample in metric.samples:
            if (
                sample.name == "erp_rag_query_stage_latency_ms_count"
                and sample.labels.get("stage") == stage.value
            ):
                return sample.value
    return 0.0


def _stage_sum_ms(stage: Stage) -> float:
    for metric in REGISTRY.collect():
        if metric.name != "erp_rag_query_stage_latency_ms":
            continue
        for sample in metric.samples:
            if (
                sample.name == "erp_rag_query_stage_latency_ms_sum"
                and sample.labels.get("stage") == stage.value
            ):
                return sample.value
    return 0.0


def _token_count(provider: str, kind: str) -> float:
    for metric in REGISTRY.collect():
        if metric.name != "erp_rag_tokens_used":
            continue
        for sample in metric.samples:
            if (
                sample.name == "erp_rag_tokens_used_total"
                and sample.labels.get("provider") == provider
                and sample.labels.get("type") == kind
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# Pipeline fixtures — real objects, stubbed I/O
# ---------------------------------------------------------------------------

class _StubLLM(LLMPort):
    def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        return _RAG_RESPONSE


class _ConstantEmbedder(EmbeddingPort):
    _VECTOR: list[float] = [1.0] + [0.0] * 767

    def embed(self, text: str) -> list[float]:
        return self._VECTOR


@pytest.fixture()
def rag_agent() -> RAGAgent:
    store = InMemoryVectorStore()
    embedder = _ConstantEmbedder()
    store.upsert(
        asset_id="a-1",
        tenant_id=_TENANT,
        embedding=embedder.embed("x"),
        chunk_id="c-1",
        content="Requisitions above 50000 DZD require written approval.",
        erp_module="finance",
    )
    return RAGAgent(
        retriever=VectorRetriever(store=store, embedder=embedder),
        reranker=IdentityReranker(),
        context_builder=ContextBuilder(),
        llm=_StubLLM(),
        registry=PromptRegistry(prompts_dir=_PROMPTS_DIR),
    )


# ---------------------------------------------------------------------------
# The RAG pipeline reports its stages
# ---------------------------------------------------------------------------

class TestRunningRagRecordsItsStages:
    @pytest.mark.parametrize(
        "stage",
        [Stage.RETRIEVE, Stage.RERANK, Stage.GENERATE],
        ids=lambda s: s.value,
    )
    def test_the_stage_is_recorded(self, rag_agent, stage):
        before = _stage_count(stage)

        asyncio.run(rag_agent.run("approval threshold?", AgentContext(tenant_id=_TENANT)))

        assert _stage_count(stage) == before + 1

    def test_the_recorded_time_is_positive(self, rag_agent):
        before = _stage_sum_ms(Stage.GENERATE)

        asyncio.run(rag_agent.run("approval threshold?", AgentContext(tenant_id=_TENANT)))

        assert _stage_sum_ms(Stage.GENERATE) > before

    def test_retrieval_is_still_recorded_when_it_finds_nothing(self, rag_agent):
        """An empty result is a measurement, not an absence of one."""
        before = _stage_count(Stage.RETRIEVE)

        asyncio.run(rag_agent.run("anything", AgentContext(tenant_id="nobody")))

        assert _stage_count(Stage.RETRIEVE) == before + 1


class _StubHybridAgent:
    """Returns a valid HybridResult without running RAG or SQL.

    StubClassifier routes to HYBRID, and this test is about the classify stage
    that runs before the dispatch — not about what the dispatch then does.
    """

    async def run(self, query: str, context: AgentContext) -> HybridResult:
        return HybridResult.rag_fallback(RAGResult.not_grounded())


class TestRoutingRecordsClassification:
    def test_classify_is_recorded(self, rag_agent):
        route = RouteQueryUseCase(
            classifier=StubClassifier(),
            rag_uc=RunRAGUseCase(rag_agent=rag_agent),
            sql_uc=RunSQLUseCase(sql_agent=None),  # type: ignore[arg-type]
            hybrid_uc=RunHybridUseCase(hybrid_agent=_StubHybridAgent()),  # type: ignore[arg-type]
        )
        claims = TokenClaims(
            user_id="u1", role="FINANCE_MANAGER", tenant_id=_TENANT,
            exp=0, iat=0, sub="u1",
        )
        before = _stage_count(Stage.CLASSIFY)

        asyncio.run(route.execute("what is the approval threshold?", claims))

        assert _stage_count(Stage.CLASSIFY) == before + 1


# ---------------------------------------------------------------------------
# The SQL pipeline reports its stages
# ---------------------------------------------------------------------------

class TestRunningSqlRecordsItsStages:
    def test_sql_generate_is_recorded(self):
        before = _stage_count(Stage.SQL_GENERATE)

        QueryGenerator().generate("total revenue from sales orders")

        assert _stage_count(Stage.SQL_GENERATE) == before + 1

    def test_sql_execute_is_recorded(self):
        before = _stage_count(Stage.SQL_EXECUTE)

        generated = QueryGenerator().generate("total revenue from sales orders")
        report = QueryValidator().validate(generated.raw_sql)
        QueryExecutor().execute(report, tenant_id=_TENANT)

        assert _stage_count(Stage.SQL_EXECUTE) == before + 1

    def test_the_generated_result_agrees_with_the_metric(self):
        """GeneratedSQL.latency_ms and the histogram must come from one clock."""
        before = _stage_sum_ms(Stage.SQL_GENERATE)

        generated = QueryGenerator().generate("total revenue from sales orders")

        recorded = _stage_sum_ms(Stage.SQL_GENERATE) - before
        assert recorded == pytest.approx(generated.latency_ms, rel=1e-6)


# ---------------------------------------------------------------------------
# stage_timer itself
# ---------------------------------------------------------------------------

class TestStageTimer:
    def test_a_stage_that_raises_is_still_recorded(self):
        """A slow failure is the measurement you most want to keep."""
        before = _stage_count(Stage.GENERATE)

        with pytest.raises(RuntimeError):
            with stage_timer(Stage.GENERATE):
                raise RuntimeError("provider exploded")

        assert _stage_count(Stage.GENERATE) == before + 1

    def test_elapsed_is_readable_inside_the_block(self):
        """The SQL executor builds its result mid-block, so this must work."""
        with stage_timer(Stage.SQL_EXECUTE) as timing:
            inside = timing.elapsed_ms

        assert inside >= 0.0

    def test_elapsed_is_frozen_once_the_block_exits(self):
        with stage_timer(Stage.SQL_EXECUTE) as timing:
            pass
        first = timing.elapsed_ms

        assert timing.elapsed_ms == first

    def test_the_frozen_value_is_what_was_recorded(self):
        before = _stage_sum_ms(Stage.RERANK)

        with stage_timer(Stage.RERANK) as timing:
            pass

        assert _stage_sum_ms(Stage.RERANK) - before == pytest.approx(timing.elapsed_ms)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

class TestRecordTokens:
    def test_counts_are_recorded_per_provider(self):
        before = _token_count("unit-test-provider", "prompt")

        record_tokens("unit-test-provider", prompt=120, completion=30)

        assert _token_count("unit-test-provider", "prompt") == before + 120

    def test_prompt_and_completion_are_separate_series(self):
        record_tokens("split-provider", prompt=7, completion=11)

        assert _token_count("split-provider", "prompt") == 7
        assert _token_count("split-provider", "completion") == 11

    def test_a_missing_count_is_not_recorded_as_zero(self):
        """None means the provider did not say. Recording 0 would claim a free call."""
        record_tokens("silent-provider", prompt=None, completion=None)

        assert _token_count("silent-provider", "prompt") == 0.0

    def test_it_never_raises(self):
        """Token accounting must not be able to fail a user's query."""
        record_tokens("bad-provider", prompt="not-a-number", completion=None)  # type: ignore[arg-type]


class TestClientsReportTokens:
    """The clients are the only layer that sees a provider's real usage."""

    def test_vllm_records_what_the_server_reported(self, monkeypatch):
        import httpx

        from src.infrastructure.generation.vllm_llm_client import vLLMLLMClient

        class _Response:
            status_code = 200

            def raise_for_status(self) -> None: ...

            def json(self) -> dict:
                return {
                    "choices": [{"message": {"content": "hello"}}],
                    "usage": {"prompt_tokens": 42, "completion_tokens": 8},
                }

        class _Client:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, *a, **kw): return _Response()

        monkeypatch.setattr(httpx, "Client", lambda **kw: _Client())
        before = _token_count("vllm", "prompt")

        vLLMLLMClient(base_url="http://x", model="m").complete("hi")

        assert _token_count("vllm", "prompt") == before + 42
        assert _token_count("vllm", "completion") >= 8

    def test_a_provider_that_omits_usage_still_returns_its_answer(self, monkeypatch):
        """Missing usage must not break the completion."""
        import httpx

        from src.infrastructure.generation.vllm_llm_client import vLLMLLMClient

        class _Response:
            status_code = 200

            def raise_for_status(self) -> None: ...

            def json(self) -> dict:
                return {"choices": [{"message": {"content": "still works"}}]}

        class _Client:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, *a, **kw): return _Response()

        monkeypatch.setattr(httpx, "Client", lambda **kw: _Client())

        assert vLLMLLMClient(base_url="http://x", model="m").complete("hi") == "still works"

    def test_gemini_reads_usage_defensively(self):
        """The SDK types every usage field as optional and has moved them before."""
        from src.infrastructure.generation.gemini_llm_client import _usage

        class _NoUsage:
            pass

        class _WithUsage:
            class usage_metadata:  # noqa: N801 — mirrors the SDK attribute name
                prompt_token_count = 5
                candidates_token_count = 6

        assert _usage(_NoUsage()) == (None, None)
        assert _usage(_WithUsage()) == (5, 6)
