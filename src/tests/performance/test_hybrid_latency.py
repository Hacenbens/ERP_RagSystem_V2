"""
Performance test — Sprint 7 Task 13.

Measures wall-clock latency for 10 sequential hybrid queries posted to
POST /api/v1/query via TestClient (no real network, no real LLM).

Acceptance criteria:
  - p95 latency ≤ 8 000 ms
  - All 10 queries return HTTP 200

Run explicitly:
    pytest -m performance src/tests/performance/test_hybrid_latency.py -v -s
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agents.hybrid_agent import HybridAgent
from src.agents.rag_agent import RAGAgent
from src.agents.sql_agent import SQLAgent
from src.domain.ports.llm_port import LLMPort
from src.infrastructure.di.container import DIContainer
from src.infrastructure.erp.query_executor import QueryExecutor
from src.infrastructure.erp.query_generator import QueryGenerator
from src.infrastructure.erp.query_validator import QueryValidator
from src.infrastructure.nlp.stub_classifier import StubClassifier
from src.infrastructure.rag.context_builder import ContextBuilder
from src.infrastructure.rag.reranker import IdentityReranker
from src.infrastructure.rag.vector_retriever import VectorRetriever
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.prompts.registry import PromptRegistry
from src.routes.query import router as query_router
from src.use_cases.route_query import RouteQueryUseCase
from src.use_cases.run_hybrid import RunHybridUseCase
from src.use_cases.run_rag import RunRAGUseCase
from src.use_cases.run_sql import RunSQLUseCase

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_WARMUP = 3
_SAMPLE_SIZE = 10
_P95_THRESHOLD_MS = 8_000

_PROMPTS_DIR = Path(__file__).parents[3] / "src" / "prompts"

_TENANT_ID = "perf-tenant"
_ROLE = "FINANCE_MANAGER"

# ---------------------------------------------------------------------------
# Stub LLM — identical to test_hybrid_agent.py
# ---------------------------------------------------------------------------

_RAG_RESPONSE = json.dumps({
    "grounded": True,
    "answer": "Based on the available context, here is the answer.",
    "cited_chunks": [],
    "confidence": 0.85,
    "insufficient_data_for": [],
})

_HYBRID_RESPONSE = json.dumps({
    "merged_answer": "Synthesized answer from SQL and RAG.",
    "sql_contribution": "SQL returned relevant records.",
    "rag_contribution": "RAG retrieved applicable policy text.",
    "contradictions": [],
    "overall_confidence": 0.85,
    "cited_chunks": [],
    "sql_tables_used": [],
})


class _StubLLM(LLMPort):
    def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        if "sql_contribution" in prompt:
            return _HYBRID_RESPONSE
        return _RAG_RESPONSE


class _ConstantEmbedder:
    _VECTOR: list[float] = [1.0] + [0.0] * 767

    def embed(self, text: str) -> list[float]:
        return self._VECTOR


# ---------------------------------------------------------------------------
# Seed chunks
# ---------------------------------------------------------------------------

_SEED_CHUNKS = [
    ("chunk-finance-1",    "finance",    "VAT rates for pharmaceutical products are 0% under EU regulation."),
    ("chunk-finance-2",    "finance",    "Invoice payment terms default to NET-30 for all standard accounts."),
    ("chunk-inventory-1",  "inventory",  "Minimum stock levels trigger automatic reorder at 20% threshold."),
    ("chunk-procurement-1","procurement","Emergency procurement above 50 000 EUR requires CFO approval."),
    ("chunk-crm-1",        "crm",        "Tier-1 customer escalations must be resolved within 4 business hours."),
    ("chunk-warehouse-1",  "warehouse",  "Export compliance requires EUR1 certificate for non-EU shipments."),
]

_QUERIES = [
    {"query": "What are the VAT rules for pharmaceutical products?",        "erp_module": "finance"},
    {"query": "What is the default invoice payment term?",                  "erp_module": "finance"},
    {"query": "When does automatic reorder trigger for low stock?",         "erp_module": "inventory"},
    {"query": "What approval is needed for emergency procurement?",         "erp_module": "procurement"},
    {"query": "What is the SLA for tier-1 escalations?",                   "erp_module": "crm"},
    {"query": "What documents are required for non-EU shipments?",          "erp_module": "warehouse"},
    {"query": "Summarize financial policies and inventory reorder rules.",  "erp_module": "finance"},
    {"query": "Compare procurement approval thresholds to CRM SLAs.",      "erp_module": "procurement"},
    {"query": "What are the stock and shipment compliance requirements?",   "erp_module": "warehouse"},
    {"query": "Give an overview of all ERP policy documents.",              "erp_module": "finance"},
]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _seed_vector_store(store: InMemoryVectorStore) -> None:
    embedder = _ConstantEmbedder()
    for chunk_id, erp_module, content in _SEED_CHUNKS:
        store.upsert(
            asset_id="perf-asset-001",
            tenant_id=_TENANT_ID,
            embedding=embedder.embed(content),
            chunk_id=chunk_id,
            content=content,
            erp_module=erp_module,
        )


def _build_test_app() -> FastAPI:
    llm = _StubLLM()
    embedder = _ConstantEmbedder()

    vector_store = InMemoryVectorStore()
    _seed_vector_store(vector_store)

    retriever = VectorRetriever(store=vector_store, embedder=embedder)
    reranker = IdentityReranker()
    context_builder = ContextBuilder()
    registry = PromptRegistry(prompts_dir=_PROMPTS_DIR)

    rag_agent = RAGAgent(
        retriever=retriever,
        reranker=reranker,
        context_builder=context_builder,
        llm=llm,
        registry=registry,
    )
    sql_agent = SQLAgent(
        generator=QueryGenerator(),
        validator=QueryValidator(),
        executor=QueryExecutor(),
    )
    hybrid_agent = HybridAgent(
        rag_agent=rag_agent,
        sql_agent=sql_agent,
        llm=llm,
        registry=registry,
    )

    rag_uc = RunRAGUseCase(rag_agent=rag_agent)
    sql_uc = RunSQLUseCase(sql_agent=sql_agent)
    hybrid_uc = RunHybridUseCase(hybrid_agent=hybrid_agent)
    route_uc = RouteQueryUseCase(
        classifier=StubClassifier(),
        rag_uc=rag_uc,
        sql_uc=sql_uc,
        hybrid_uc=hybrid_uc,
    )

    container = DIContainer()
    container.register("route_query_use_case", route_uc)

    app = FastAPI()
    app.state.container = container
    app.include_router(query_router)

    @app.middleware("http")
    async def _inject_claims(request, call_next):
        request.state.tenant_id = _TENANT_ID
        request.state.role = _ROLE
        request.state.user_id = "perf-user-001"
        return await call_next(request)

    return app


# ---------------------------------------------------------------------------
# Module-level client (built once for the whole module)
# ---------------------------------------------------------------------------

_app = _build_test_app()
_client = TestClient(_app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.performance
class TestHybridAgentLatency:
    """p95 wall-clock latency for 10 sequential hybrid queries must be ≤ 8 000 ms."""

    def test_p95_latency_within_threshold(self):
        # warm-up
        for i in range(_WARMUP):
            q = _QUERIES[i % len(_QUERIES)]
            _client.post("/api/v1/query", json=q)

        # timed sample
        times_ms: list[float] = []
        for i in range(_SAMPLE_SIZE):
            q = _QUERIES[i % len(_QUERIES)]
            t0 = time.perf_counter()
            resp = _client.post("/api/v1/query", json=q)
            elapsed_ms = (time.perf_counter() - t0) * 1_000
            times_ms.append(elapsed_ms)
            print(
                f"  query {i+1:02d}/{_SAMPLE_SIZE}  {elapsed_ms:7.1f} ms"
                f"  status={resp.status_code}"
                f"  intent={resp.json().get('intent', '?')}"
            )
            assert resp.status_code == 200, (
                f"Query {i+1} returned HTTP {resp.status_code}: {resp.text}"
            )

        p95_ms = sorted(times_ms)[int(0.95 * _SAMPLE_SIZE)]
        print(
            f"\n  min={min(times_ms):.1f} ms  "
            f"max={max(times_ms):.1f} ms  "
            f"p95={p95_ms:.1f} ms  "
            f"threshold={_P95_THRESHOLD_MS} ms"
        )

        assert p95_ms <= _P95_THRESHOLD_MS, (
            f"p95 latency {p95_ms:.1f} ms exceeds threshold {_P95_THRESHOLD_MS} ms"
        )
