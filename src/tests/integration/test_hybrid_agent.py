"""
Integration test — Sprint 7 Task 12
20 hybrid queries posted to POST /api/v1/query via TestClient.

All I/O is mocked:
  - LLMPort.complete() returns fixture JSON matching the RAG and Hybrid schemas
  - InMemoryVectorStore seeded with ERP domain chunks
  - QueryExecutor uses InMemoryExecutor (no real PG connection)
"""
from __future__ import annotations

import json
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
# Paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"
_PROMPTS_DIR = Path(__file__).parents[3] / "src" / "prompts"

# ---------------------------------------------------------------------------
# Stub LLM
# ---------------------------------------------------------------------------

_RAG_RESPONSE = json.dumps({
    "grounded": True,
    "answer": "Based on the available context, here is the answer.",
    "cited_chunks": [],
    "confidence": 0.85,
    "insufficient_data_for": [],
})

_HYBRID_RESPONSE = json.dumps({
    "merged_answer": "Based on both structured data and policy documents, here is a synthesized answer.",
    "sql_contribution": "SQL returned relevant records from the ERP database.",
    "rag_contribution": "RAG retrieved applicable policy and procedure text.",
    "contradictions": [],
    "overall_confidence": 0.85,
    "cited_chunks": [],
    "sql_tables_used": [],
})


class _StubLLM(LLMPort):
    """Returns schema-valid JSON without calling a real language model.

    Detects context from the prompt text:
    - Hybrid merger prompt contains 'sql_contribution' in its instructions.
    - RAG prompt does not.
    """

    def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        if "sql_contribution" in prompt:
            return _HYBRID_RESPONSE
        return _RAG_RESPONSE


# ---------------------------------------------------------------------------
# Constant embedder — gives non-zero cosine similarity in InMemoryVectorStore
# ---------------------------------------------------------------------------

class _ConstantEmbedder:
    """Returns the same unit vector for every text, so all chunks score 1.0."""

    _VECTOR: list[float] = [1.0] + [0.0] * 767

    def embed(self, text: str) -> list[float]:
        return self._VECTOR


# ---------------------------------------------------------------------------
# Test seed chunks
# ---------------------------------------------------------------------------

_SEED_CHUNKS = [
    ("chunk-finance-1",   "finance",    "VAT rates for pharmaceutical products are 0% under EU regulation."),
    ("chunk-finance-2",   "finance",    "Invoice payment terms default to NET-30 for all standard accounts."),
    ("chunk-finance-3",   "finance",    "Medical device VAT exemption applies under directive 2017/745."),
    ("chunk-inventory-1", "inventory",  "Minimum stock levels trigger automatic reorder at 20% threshold."),
    ("chunk-inventory-2", "inventory",  "Cycle counting policy requires quarterly reconciliation per warehouse."),
    ("chunk-procurement-1","procurement","Emergency procurement above 50 000 EUR requires CFO approval."),
    ("chunk-procurement-2","procurement","Supplier SLA defines delivery within 5 business days for standard orders."),
    ("chunk-crm-1",        "crm",       "Tier-1 customer escalations must be resolved within 4 business hours."),
    ("chunk-crm-2",        "crm",       "Customer onboarding checklist includes KYC, contract signing, and training."),
    ("chunk-warehouse-1",  "warehouse", "Export compliance requires EUR1 certificate for non-EU shipments."),
    ("chunk-warehouse-2",  "warehouse", "Goods received procedure mandates 48-hour inspection window."),
]

_TENANT_ID = "test-tenant"
_ASSET_ID = "seed-asset-001"
_ROLE = "FINANCE_MANAGER"


def _seed_vector_store(store: InMemoryVectorStore) -> None:
    embedder = _ConstantEmbedder()
    for chunk_id, erp_module, content in _SEED_CHUNKS:
        store.upsert(
            asset_id=_ASSET_ID,
            tenant_id=_TENANT_ID,
            embedding=embedder.embed(content),
            chunk_id=chunk_id,
            content=content,
            erp_module=erp_module,
        )


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

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
        request.state.user_id = "test-user-001"
        return await call_next(request)

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    app = _build_test_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="module")
def queries() -> list[dict]:
    with open(_FIXTURES_DIR / "hybrid_test_queries.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHybridQueriesEndToEnd:

    def test_fixture_contains_20_queries(self, queries):
        assert len(queries) == 20

    def test_fixture_has_at_least_5_rag_only_queries(self, queries):
        rag_only = [q for q in queries if not q["expected_sql_source"]]
        assert len(rag_only) >= 5

    @pytest.mark.parametrize("query_fixture", [
        pytest.param(i, id=f"HQ-{i+1:03d}") for i in range(20)
    ])
    def test_query_returns_200(self, client, queries, query_fixture):
        q = queries[query_fixture]
        resp = client.post(
            "/api/v1/query",
            json={"query": q["query"], "erp_module": q["erp_module"]},
        )
        assert resp.status_code == 200, f"[{q['id']}] unexpected status {resp.status_code}: {resp.text}"

    @pytest.mark.parametrize("query_fixture", [
        pytest.param(i, id=f"HQ-{i+1:03d}") for i in range(20)
    ])
    def test_query_intent_is_valid(self, client, queries, query_fixture):
        q = queries[query_fixture]
        resp = client.post(
            "/api/v1/query",
            json={"query": q["query"], "erp_module": q["erp_module"]},
        )
        assert resp.json()["intent"] in ("HYBRID", "RAG", "SQL"), \
            f"[{q['id']}] unexpected intent: {resp.json()['intent']}"

    @pytest.mark.parametrize("query_fixture", [
        pytest.param(i, id=f"HQ-{i+1:03d}")
        for i, q in enumerate(
            json.load(open(Path(__file__).parents[1] / "fixtures" / "hybrid_test_queries.json"))
        )
        if q["expected_sql_source"]
    ])
    def test_expected_sql_source_present(self, client, queries, query_fixture):
        q = queries[query_fixture]
        resp = client.post(
            "/api/v1/query",
            json={"query": q["query"], "erp_module": q["erp_module"]},
        )
        result = resp.json()["result"]
        assert result.get("sql_result") is not None, \
            f"[{q['id']}] sql_result missing but expected_sql_source=true"

    @pytest.mark.parametrize("query_fixture", [
        pytest.param(i, id=f"HQ-{i+1:03d}")
        for i, q in enumerate(
            json.load(open(Path(__file__).parents[1] / "fixtures" / "hybrid_test_queries.json"))
        )
        if q["expected_rag_source"]
    ])
    def test_expected_rag_source_present(self, client, queries, query_fixture):
        q = queries[query_fixture]
        resp = client.post(
            "/api/v1/query",
            json={"query": q["query"], "erp_module": q["erp_module"]},
        )
        result = resp.json()["result"]
        assert result.get("rag_result") is not None, \
            f"[{q['id']}] rag_result missing but expected_rag_source=true"
