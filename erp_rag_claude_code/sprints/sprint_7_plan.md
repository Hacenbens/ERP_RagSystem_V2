# Sprint 7 — Hybrid Agent — Task Plan
**Branch:** `sprint-7/hybrid-agent`
**Date planned:** 2026-04-23
**Source of truth:** `docs/source_of_truth.md` §SPRINT 7 + §9 + §16

---

## Codebase Audit Summary

| Status | Item |
|--------|------|
| ✓ EXISTS | `src/infrastructure/erp/query_executor.py` — `ExecutionResult` + `QueryExecutor` |
| ✓ EXISTS | `src/infrastructure/erp/query_generator.py` + `query_validator.py` |
| ✓ EXISTS | `src/domain/ports/vector_store_port.py` — tracking only, NO search method yet |
| ✓ EXISTS | `src/infrastructure/vector_store/in_memory_vector_store.py` |
| ✓ EXISTS | `src/infrastructure/di/container.py` — `DIContainer` |
| ✓ EXISTS | `src/infrastructure/auth/erp_rbac_policy.py` — `MODULE_ACCESS_MATRIX` |
| ✓ EXISTS | `src/observability/prometheus_metrics.py` — `HYBRID_SUCCESS_RATE` + `HYBRID_LATENCY` already defined |
| ✓ EXISTS | `src/middleware/` — all 5 layers complete |
| ✓ EXISTS | `src/use_cases/auth_user.py` — canonical use-case path pattern |
| ✗ MISSING | `src/domain/models/` — entire sub-package |
| ✗ MISSING | `src/agents/` — entire layer |
| ✗ MISSING | `src/infrastructure/rag/` — no RAG retrieval infra |
| ✗ MISSING | `src/prompts/` — no prompt registry or YAML files |
| ✗ MISSING | `src/use_cases/run_rag.py`, `run_hybrid.py`, `route_query.py` |
| ✗ MISSING | `src/routes/query.py` |
| ✗ MISSING | `src/infrastructure/nlp/query_classifier.py` |

### Flags for Executor

> **PATH:** `src/application/use_cases/` (from source_of_truth §9.3) does not exist.
> Use `src/use_cases/` to match the existing codebase pattern.

> **CLASSIFIER:** Full LLM classifier is Sprint 9. This sprint builds a `StubClassifier`
> that always returns `HYBRID` — wired only in tests, never in production container.

> **VECTOR SEARCH:** `VectorStorePort` has no `search_similar()` method. TASK 2 adds it.
> `InMemoryVectorStore` implements cosine similarity search. Milvus deferred to Sprint 8.

> **METRICS:** `HYBRID_SUCCESS_RATE` and `HYBRID_LATENCY` already exist in
> `prometheus_metrics.py`. Do NOT redefine them. TASK 11 adds `HYBRID_PARTIAL_RATE` only.

> **LLM CALLS:** All integration tests mock `LLMPort.complete()` via monkeypatch.
> No real API key required for this sprint to pass DoD.

---

## Task Status

| Task | Title | Status |
|------|-------|--------|
| TASK 1 | Domain models | ✅ DONE (commit 4ae295d) |
| TASK 2 | Extend VectorStorePort + InMemoryVectorStore | ✅ DONE (commits 3e5e3f3, 7cf1f95) |
| TASK 3 | VectorRetriever + EmbeddingPort | ✅ DONE (commit 735f2e6) |
| TASK 4 | Reranker + ContextBuilder | ✅ DONE (uncommitted — fixes applied 2026-04-25) |
| TASK 5 | Prompt registry + YAML files | ✅ DONE (2026-04-25) |
| TASK 6 | StubClassifier | ⬜ TODO |
| TASK 7 | BaseAgent + SQLAgent + RAGAgent | ⬜ TODO |
| TASK 8 | HybridAgent | ⬜ TODO |
| TASK 9 | Use cases: RunRAG + RunHybrid + RouteQuery | ⬜ TODO |
| TASK 10 | DI wiring + POST /api/v1/query route | ⬜ TODO |
| TASK 11 | HYBRID_PARTIAL_RATE metric | ⬜ TODO |
| TASK 12 | Integration test: 20 hybrid queries | ⬜ TODO |
| TASK 13 | Performance test: p95 < 8s | ⬜ TODO |
| TASK 14 | Extend Chunk with chunk_id | ⬜ TODO |
| TASK 15 | LocalAssetStorage | ⬜ TODO |
| TASK 16 | InMemoryChunkStore + MongoChunkStore | ⬜ TODO |
| TASK 17 | CeleryJobDispatcher | ⬜ TODO |
| TASK 18 | Refactor IngestAssetUseCase | ⬜ TODO |
| TASK 19 | Refactor EmbedAssetUseCase | ⬜ TODO |
| TASK 20 | POST /api/assets/upload route | ⬜ TODO |
| TASK 21 | Wire new ports in factory.py | ⬜ TODO |

---

## Task Dependency Graph

```
── HYBRID AGENT CHAIN ──────────────────────────────────────────────────
TASK 1 (domain models) ──────────────────────────────────────┐  [DONE]
TASK 5 (prompts) ────────────────────────────────────────────┤
TASK 2 (extend port) ← TASK 1                                │  [DONE]
TASK 3 (retriever)   ← TASK 2                                │  [DONE]
TASK 4 (reranker+ctx)← TASK 3                                │  [DONE]
TASK 6 (classifier stub) ← TASK 1                            ▼
TASK 7 (base+sql+rag agents) ← TASK 4 + TASK 5 + TASK 6
TASK 8 (hybrid agent) ← TASK 7
TASK 11 (metrics)     ← TASK 8 (parallel with TASK 9)
TASK 9 (use cases)    ← TASK 8
TASK 10 (DI + route)  ← TASK 9
TASK 12 (integration test 20 queries) ← TASK 10
TASK 13 (latency test) ← TASK 12

── INGESTION PIPELINE CHAIN ────────────────────────────────────────────
TASK 14 (chunk_id)    ─────────────────────────────────────────────────┐
TASK 15 (LocalAssetStorage)                                            │
TASK 16 (ChunkStore)  ← TASK 14                                        │
TASK 17 (CeleryJobDispatcher)                                          │
TASK 18 (IngestAssetUseCase) ← TASK 14 + TASK 15 + TASK 16            │
TASK 19 (EmbedAssetUseCase)  ← TASK 14 + TASK 16                      │
TASK 20 (upload route)       ← TASK 15 + TASK 17                      │
TASK 21 (factory wiring)     ← TASK 15+16+17+18+19 ───────────────────┘
```

---

## TASK 1 — Domain models: RoutingDecision, RAGResult, SQLResult, HybridResult, ScoredChunk

```
File:        src/domain/models/__init__.py          (CREATE)
             src/domain/models/routing_decision.py  (CREATE)
             src/domain/models/rag_result.py        (CREATE)
             src/domain/models/sql_result.py        (CREATE)
             src/domain/models/hybrid_result.py     (CREATE)
             src/domain/models/scored_chunk.py      (CREATE)
Action:      CREATE
Effort:      0.5d
Depends on:  NONE
```

**Acceptance criteria:**
- All files use `from __future__ import annotations` and `@dataclass(frozen=True)`
- No imports from `infrastructure/` — pure domain
- `ScoredChunk(chunk_id: str, content: str, score: float, source: str, erp_module: str | None)`
- `RoutingDecision(intent: QueryIntent, confidence: float, erp_module: ErpModule | None, reason: str)`
- `RAGResult(answer: str | None, cited_chunks: list[str], grounding_score: float, confidence: float, insufficient_data_for: list[str], grounded: bool)`
- `SQLResult(rows: list[dict], query: str, latency_ms: float, tables_used: list[str], row_count: int)`
- `HybridResult(rag_result: RAGResult | None, sql_result: SQLResult | None, merged_answer: str | None, sql_contribution: str, rag_contribution: str, contradictions: list[str], overall_confidence: float, rag_only: bool, sql_only: bool)`
- `__init__.py` exports all 5 models in `__all__`

**Test file:** `src/tests/unit/test_hybrid_domain_models.py` (CREATE)

---

## TASK 2 — Extend VectorStorePort with search_similar()

```
File:        src/domain/ports/vector_store_port.py               (MODIFY)
             src/infrastructure/vector_store/in_memory_vector_store.py  (MODIFY)
             src/infrastructure/vector_store/mongo_vector_store.py      (MODIFY)
Action:      MODIFY
Effort:      0.5d
Depends on:  TASK 1
```

**Acceptance criteria:**
- `VectorStorePort` gains one new abstract method:
  ```python
  @abstractmethod
  def search_similar(
      self,
      query_embedding: list[float],
      k: int,
      tenant_id: str,
      erp_module: str | None = None,
  ) -> list[ScoredChunk]: ...
  ```
- `InMemoryVectorStore` implements cosine similarity search over stored vectors
  (store must also accept `upsert(asset_id, tenant_id, embedding: list[float], chunk_id: str, content: str, erp_module: str)`)
- `MongoVectorStore` raises `NotImplementedError("Milvus wiring deferred to Sprint 8")`
- All existing `has_vectors` / `save_vectors` / `count` tests still pass

**Test file:** `src/tests/unit/test_vector_store_port.py` (EXTEND — add search_similar tests)

---

## TASK 3 — RAG infrastructure: VectorRetriever

```
File:        src/infrastructure/rag/__init__.py         (CREATE)
             src/infrastructure/rag/vector_retriever.py (CREATE)
Action:      CREATE
Effort:      0.5d
Depends on:  TASK 2
```

**Acceptance criteria:**
- `VectorRetriever(store: VectorStorePort, embedder: EmbeddingPort)`
- `retrieve(query: str, k: int, tenant_id: str, erp_module: str | None) -> list[ScoredChunk]`
  1. Calls `embedder.embed(query)` → `list[float]`
  2. Calls `store.search_similar(embedding, k, tenant_id, erp_module)` → `list[ScoredChunk]`
  3. Logs `rag.retriever.done` with `chunk_count`, `tenant_id`
- `EmbeddingPort` is a simple ABC in `src/domain/ports/embedding_port.py` (CREATE if not exists):
  `embed(text: str) -> list[float]`
- `NoopEmbeddingProvider` in `src/infrastructure/rag/noop_embedding_provider.py` returns `[0.0] * 768`
  — used in tests only

**Test file:** `src/tests/unit/test_vector_retriever.py` (CREATE)

---

## TASK 4 — RAG infrastructure: Reranker + ContextBuilder

```
File:        src/infrastructure/rag/reranker.py        (CREATE)
             src/infrastructure/rag/context_builder.py (CREATE)
Action:      CREATE
Effort:      1d
Depends on:  TASK 3
```

**Acceptance criteria:**

`CrossEncoderReranker`:
- `rerank(query: str, docs: list[ScoredChunk], top_k: int) -> list[ScoredChunk]`
- Uses `sentence-transformers` cross-encoder model (model name injected, default `cross-encoder/ms-marco-MiniLM-L-6-v2`)
- Falls back to identity sort (by original score) when model unavailable in test env
- `IdentityReranker` (no-op, sorts by score desc) created alongside for tests

`ContextBuilder`:
- `build(chunks: list[ScoredChunk], max_tokens: int = 3000) -> str`
- Assembles chunks as: `[chunk_id] (score=X, source=Y)\n{content}\n\n`
- Truncates at `max_tokens` estimated tokens (1 token ≈ 4 chars)
- Logs `rag.context_builder.done` with `chunks_used`, `total_chars`, `truncated: bool`

**Test file:** `src/tests/unit/test_rag_infrastructure.py` (CREATE)
Tests: reranker reorders correctly, context_builder truncates at limit, identity reranker passthrough

---

## TASK 5 — Prompt registry + YAML files

```
File:        src/prompts/__init__.py                             (CREATE)
             src/prompts/registry.py                             (CREATE)
             src/prompts/schemas/rag_output.schema.json          (CREATE)
             src/prompts/schemas/hybrid_output.schema.json       (CREATE)
             src/prompts/versions/rag_answer_v1.yaml             (CREATE)
             src/prompts/versions/hybrid_orchestrator_v1.yaml    (CREATE)
Action:      CREATE
Effort:      0.5d
Depends on:  NONE (parallel with TASK 3–4)
```

**Acceptance criteria:**

`PromptVersion` dataclass fields: `id`, `prompt_name`, `version`, `prompt_text`, `parameters` (dict), `deployment_status: Literal["shadow","canary","production","deprecated"]`, `schema_path: str | None`

`PromptRegistry(prompts_dir: str)`:
- `resolve(name: str, version: str = "production") -> PromptVersion`
  loads all YAML files in `prompts_dir/versions/`, finds the one matching `prompt_name=name` AND `deployment_status=version` (or `id=f"{name}_{version}"`)
- `validate_output(pv: PromptVersion, output: dict) -> None`
  loads JSON schema from `pv.schema_path`, runs `jsonschema.validate(output, schema)`
  raises `jsonschema.ValidationError` on mismatch — caller must catch

YAML files contain prompts verbatim from `source_of_truth.md §11.3` (rag_answer_v1) and `§11.4` (hybrid_orchestrator_v1).

JSON schemas validate the JSON output fields of each prompt (grounded, answer, cited_chunks, etc.).

**Test file:** `src/tests/unit/test_prompt_registry.py` (CREATE)
Tests: resolve finds production version, validate_output passes valid dict, raises on invalid dict, raises on unknown prompt name

---

## TASK 6 — Minimal classifier port + StubClassifier

```
File:        src/domain/ports/query_classifier_port.py  (CREATE)
             src/infrastructure/nlp/__init__.py          (CREATE — if not exists)
             src/infrastructure/nlp/stub_classifier.py   (CREATE)
Action:      CREATE
Effort:      0.5d
Depends on:  TASK 1
```

**Acceptance criteria:**
- `AbstractQueryClassifier(ABC)`:
  `classify(query: str) -> RoutingDecision`
- `StubClassifier(AbstractQueryClassifier)`:
  always returns `RoutingDecision(intent=QueryIntent.HYBRID, confidence=1.0, erp_module=None, reason="stub")`
  File MUST have top comment: `# Sprint 9 replaces this with LLMQueryClassifier`
- `StubClassifier` is NEVER registered in production DI container — only in test fixtures

**Test file:** `src/tests/unit/test_stub_classifier.py` (CREATE)

---

## TASK 7 — BaseAgent + SQLAgent + RAGAgent

```
File:        src/agents/__init__.py    (CREATE)
             src/agents/base_agent.py  (CREATE)
             src/agents/sql_agent.py   (CREATE)
             src/agents/rag_agent.py   (CREATE)
Action:      CREATE
Effort:      1d
Depends on:  TASK 4, TASK 5, TASK 6
```

**Acceptance criteria:**

`BaseAgent(ABC)`:
```python
@abstractmethod
async def run(self, query: str, tenant_id: str, erp_module: str | None) -> Any: ...
```

`SQLAgent(BaseAgent)`:
- Constructor: `(generator: QueryGenerator, validator: QueryValidator, executor: QueryExecutor)`
- `run()` calls Stage 1 → 2 → 3 of existing SQL pipeline
- Maps `ExecutionResult` → `SQLResult` domain model
- On any stage failure: raises `SQLAgentError(message, stage: int)`
- Logs `sql_agent.start`, `sql_agent.done`, `sql_agent.error`

`RAGAgent(BaseAgent)`:
- Constructor: `(retriever: VectorRetriever, reranker: CrossEncoderReranker, context_builder: ContextBuilder, llm: LLMPort, prompt_registry: PromptRegistry)`
- `run()`:
  1. `retriever.retrieve(query, k=20, tenant_id, erp_module)` → chunks
  2. `reranker.rerank(query, chunks, top_k=5)` → ranked
  3. `context_builder.build(ranked)` → context_str
  4. Resolve `rag_answer_v1` prompt, fill `{{masked_query}}` + `{{chunks}}`
  5. `llm.complete(prompt)` → raw JSON string
  6. Parse + validate against schema → `RAGResult`
- On LLM error: raises `RAGAgentError`
- Logs `rag_agent.start`, `rag_agent.done`, `rag_agent.error`

`LLMPort(ABC)` in `src/domain/ports/llm_port.py` (CREATE if not exists):
```python
@abstractmethod
async def complete(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str: ...
```

**Test file:** `src/tests/unit/test_agents.py` (CREATE)
Tests: sql_agent maps ExecutionResult to SQLResult, rag_agent calls retriever+reranker+llm in order,
sql_agent raises SQLAgentError on stage failure, rag_agent raises RAGAgentError on LLM failure

---

## TASK 8 — HybridAgent: asyncio.gather + partial failure

```
File:        src/agents/hybrid_agent.py  (CREATE)
Action:      CREATE
Effort:      1.5d
Depends on:  TASK 7
```

**Acceptance criteria:**
```python
class HybridAgent(BaseAgent):
    def __init__(
        self,
        rag_agent: RAGAgent,
        sql_agent: SQLAgent,
        merger_llm: LLMPort,
        prompt_registry: PromptRegistry,
    ) -> None: ...

    async def run(
        self, query: str, tenant_id: str, erp_module: str | None
    ) -> HybridResult: ...
```

Internal logic:
1. `rag_task, sql_task = asyncio.gather(rag_agent.run(...), sql_agent.run(...), return_exceptions=True)`
2. Classify outcomes:
   - Both succeed → call merger LLM with `hybrid_orchestrator_v1` prompt → parse → `HybridResult`
   - SQL is Exception, RAG succeeds → `HybridResult(sql_result=None, rag_only=True, merged_answer=None, rag_result=rag_result)` — increment `HYBRID_PARTIAL_RATE.labels("rag_only")`
   - RAG is Exception, SQL succeeds → `HybridResult(rag_result=None, sql_only=True, merged_answer=None, sql_result=sql_result)` — increment `HYBRID_PARTIAL_RATE.labels("sql_only")`
   - Both fail → raise `HybridAgentError("Both SQL and RAG agents failed")`
3. On success: increment `HYBRID_SUCCESS_RATE`, observe `HYBRID_LATENCY`
4. Validate merger LLM output against `hybrid_output.schema.json` before building `HybridResult`

**Test file:** `src/tests/unit/test_hybrid_agent.py` (CREATE)
Test cases (all using mocked agents):
- `test_both_succeed_calls_merger_llm`
- `test_sql_fails_returns_rag_only_no_exception`
- `test_rag_fails_returns_sql_only_no_exception`
- `test_both_fail_raises_hybrid_agent_error`
- `test_gather_is_truly_parallel` (mock agents sleep 1s each; total < 1.5s)
- `test_merger_validates_output_schema`
- `test_partial_rate_metric_increments_on_sql_failure`
- `test_success_metric_increments_on_both_succeed`

---

## TASK 9 — Use cases: RunRAGUseCase + RunHybridUseCase + RouteQueryUseCase

```
File:        src/use_cases/run_rag.py       (CREATE)
             src/use_cases/run_hybrid.py    (CREATE)
             src/use_cases/route_query.py   (CREATE)
Action:      CREATE
Effort:      1d
Depends on:  TASK 8
```

**Acceptance criteria:**

`RunRAGUseCase(rag_agent: RAGAgent)`:
- `async execute(query: str, tenant_id: str, erp_module: str | None) -> RAGResult`

`RunHybridUseCase(hybrid_agent: HybridAgent)`:
- `async execute(query: str, tenant_id: str, erp_module: str | None) -> HybridResult`

`RouteQueryUseCase(classifier, rag_uc, sql_uc, hybrid_uc)`:
- `async execute(query: str, user: AuthenticatedUser, tenant_id: str) -> RAGResult | SQLResult | HybridResult`
- Routing logic (from `source_of_truth.md §15.2`):
  ```python
  decision = classifier.classify(query)
  if decision.intent == BLOCKED or decision.confidence < 0.50:
      raise BlockedQueryError(decision.reason)
  if decision.confidence < 0.70:
      return await hybrid_uc.execute(...)
  if decision.intent == SQL and user.role == REPORTING_ANALYST:
      return await rag_uc.execute(...)
  # dispatch to matching use case
  ```
- Logs `route_query.intent`, `route_query.confidence`, `route_query.dispatched_to`

**Test file:** `src/tests/unit/test_hybrid_use_cases.py` (CREATE)
Tests: routes HYBRID intent to hybrid_uc, routes low-confidence to hybrid_uc,
routes BLOCKED to BlockedQueryError, REPORTING_ANALYST+SQL goes to rag_uc

---

## TASK 10 — DI wiring + POST /api/v1/query route

```
File:        src/infrastructure/di/container.py  (MODIFY)
             src/infrastructure/di/factory.py     (MODIFY)
             src/routes/query.py                  (CREATE)
Action:      MODIFY + CREATE
Effort:      0.5d
Depends on:  TASK 9
```

**Acceptance criteria:**

`container.py` — add to `REQUIRED_PORTS`:
```python
"route_query_use_case",
"rag_use_case",
"hybrid_use_case",
```

`factory.py` — add `build_query_chain(container, settings)` that wires:
```
StubClassifier()                  → "query_classifier"
InMemoryVectorStore()             → "vector_store"
NoopEmbeddingProvider()           → "embedding_provider"
VectorRetriever(store, embedder)  → "vector_retriever"
IdentityReranker()                → "reranker"
ContextBuilder()                  → "context_builder"
PromptRegistry(prompts_dir)       → "prompt_registry"
RAGAgent(...)                     → "rag_agent"
SQLAgent(...)                     → "sql_agent"
HybridAgent(...)                  → "hybrid_agent"
RunRAGUseCase(rag_agent)          → "rag_use_case"
RunHybridUseCase(hybrid_agent)    → "hybrid_use_case"
RouteQueryUseCase(...)            → "route_query_use_case"
```

`routes/query.py`:
```python
POST /api/v1/query
Request body: { "query": str, "tenant_id": str, "erp_module": str | None }
Auth: JWT required (middleware handles — no explicit check needed in route)
Returns: { "intent": str, "result": dict, "rag_only": bool, "sql_only": bool }
On BlockedQueryError → HTTP 403
On HybridAgentError → HTTP 503
```

**Test file:** `src/tests/unit/test_di_factory.py` (EXTEND — add test that `build_query_chain` binds all 3 new required ports)

---

## TASK 11 — Add HYBRID_PARTIAL_RATE metric

```
File:        src/observability/prometheus_metrics.py  (MODIFY)
Action:      MODIFY
Effort:      0.5d
Depends on:  TASK 8
```

**Acceptance criteria:**
- Add exactly ONE new metric (do NOT redefine existing ones):
  ```python
  HYBRID_PARTIAL_RATE = Counter(
      "erp_rag_hybrid_partial_total",
      "Hybrid queries that fell back to single-agent due to the other failing",
      ["fallback_mode"],   # "rag_only" | "sql_only"
  )
  ```
- Add `"HYBRID_PARTIAL_RATE"` to `__all__`
- `HybridAgent` imports and increments `HYBRID_PARTIAL_RATE.labels("rag_only")` or `labels("sql_only")`

**Test file:** `src/tests/unit/test_observability.py` (EXTEND — assert HYBRID_PARTIAL_RATE increments on partial failure)

---

## TASK 12 — Integration test: 20 hybrid queries

```
File:        src/tests/fixtures/hybrid_test_queries.json   (CREATE)
             src/tests/integration/test_hybrid_agent.py    (CREATE)
Action:      CREATE
Effort:      1d
Depends on:  TASK 10
```

**Acceptance criteria:**

`hybrid_test_queries.json` — 20 entries:
```json
[
  {
    "id": "HQ-001",
    "query": "What is the VAT rate for pharmaceutical products and how many VAT transactions did we record this quarter?",
    "tenant_id": "test-tenant",
    "erp_module": "finance",
    "expected_sql_source": true,
    "expected_rag_source": true
  },
  ...
]
```
Mix of: finance, inventory, procurement, crm, warehouse queries.
At least 5 queries where expected_sql_source=false (RAG-only fallback scenario).

`test_hybrid_agent.py`:
- Uses monkeypatched `LLMPort.complete()` returning fixture JSON responses
- Uses `InMemoryVectorStore` seeded with test chunks
- POSTs to `POST /api/v1/query` via `TestClient`
- For each query:
  - `assert response.status_code == 200`
  - `assert result["intent"] in ["HYBRID", "RAG", "SQL"]`
  - When `expected_sql_source=true`: `assert result["result"]["sql_result"] is not None`
  - When `expected_rag_source=true`: `assert result["result"]["rag_result"] is not None`
- All 20 queries must pass

**Test file:** IS the test

---

## TASK 13 — Performance test: hybrid p95 latency < 8 seconds

```
File:        src/tests/performance/test_hybrid_latency.py  (CREATE)
Action:      CREATE
Effort:      0.5d
Depends on:  TASK 12
```

**Acceptance criteria:**
- Marked `@pytest.mark.performance` — excluded from default `pytest` run
- Run 10 hybrid queries sequentially, measure wall-clock time each
- Compute p95: `sorted(times)[int(0.95 * len(times))]`
- Assert `p95_ms <= 8000`
- Uses mocked LLM (no real API) — measures system overhead only
- Prints per-query timing to stdout for visibility

**Test file:** IS the test

---

---

## TASK 14 — Extend Chunk domain model with chunk_id

```
File:        src/domain/chunk.py
Action:      MODIFY
Effort:      0.5d
Depends on:  NONE
```

**Acceptance criteria:**
- Add `chunk_id: str = field(default_factory=lambda: str(uuid4()))` to `Chunk`
- All existing tests that build `Chunk(text=..., metadata=...)` pass without change
- `chunk_id` is stable (same object, same id — no regeneration on read)

**Test file:** existing tests — no breakage is the acceptance criterion

---

## TASK 15 — LocalAssetStorage — implement AssetStoragePort

```
File:        src/infrastructure/storage/__init__.py       (CREATE — new dir)
             src/infrastructure/storage/local_asset_storage.py  (CREATE)
Action:      CREATE
Effort:      0.5d
Depends on:  NONE
```

**Acceptance criteria:**
- `LocalAssetStorage(base_path: str)` implements `AssetStoragePort`
- `save_bytes(tenant_id, asset_id, filename, content)` → writes to `{base_path}/{tenant_id}/{asset_id}/{filename}`, returns storage key
- `read_bytes(tenant_id, storage_key)` → returns bytes; raises `FileNotFoundError` if missing
- `delete_bytes(tenant_id, storage_key)` → removes file; raises `FileNotFoundError` if missing
- Cross-tenant isolation: tenant A key cannot be used to read tenant B data

**Test file:** `src/tests/unit/test_local_asset_storage.py`
- Round-trip: save → read → delete → read raises `FileNotFoundError`
- Cross-tenant isolation (tenant A cannot read tenant B storage key)
- Directory created automatically if it does not exist

---

## TASK 16 — InMemoryChunkStore + MongoChunkStore — implement ChunkStorePort

```
File:        src/infrastructure/persistence/__init__.py   (CREATE — new dir)
             src/infrastructure/persistence/chunk_store.py (CREATE)
Action:      CREATE
Effort:      1d
Depends on:  TASK 14
```

**Acceptance criteria:**
- `InMemoryChunkStore` implements `ChunkStorePort`:
  - `save_chunks(asset_id, tenant_id, chunks)` → upsert semantics (replaces, not appends); returns `len(chunks)`
  - `find_by_asset(asset_id, tenant_id)` → returns stored chunks; empty list if none
  - `delete_by_asset(asset_id, tenant_id)` → removes and returns count
  - Cross-tenant isolation: tenant A cannot see tenant B chunks
- `MongoChunkStore(collection)` implements same contract via pymongo collection
  - Upsert uses `(asset_id, tenant_id)` compound key
  - `MongoChunkStore(collection=None)` raises `NotImplementedError` on any call (test guard)

**Test file:** `src/tests/unit/test_chunk_store.py`
- `InMemoryChunkStore`: save → find → delete round-trip, re-save replaces chunks, tenant isolation
- `MongoChunkStore`: fake collection stub verifies correct pymongo calls (`delete_many` + `insert_many`)

---

## TASK 17 — CeleryJobDispatcher — implement JobDispatcherPort

```
File:        src/infrastructure/workers/celery_job_dispatcher.py  (CREATE)
Action:      CREATE
Effort:      0.5d
Depends on:  NONE
```

**Acceptance criteria:**
- `CeleryJobDispatcher` implements `JobDispatcherPort`
- `dispatch_ingest(asset_id, tenant_id, chunk_strategy)` → calls `ingest_asset.delay(...)`, returns `task.id`
- `dispatch_embed(asset_id, tenant_id, chunk_strategy)` → calls `embed_asset.delay(...)`, returns `task.id`
- Testable without a real broker: accepts an optional `_task_factory` dict for injection

**Test file:** `src/tests/unit/test_celery_job_dispatcher.py`
- `dispatch_ingest` calls delay with correct positional args, returns task id string
- `dispatch_embed` same
- Both methods return the Celery task id, not the `AsyncResult` object

---

## TASK 18 — Refactor IngestAssetUseCase — wire AssetStoragePort + ChunkStorePort

```
File:        src/use_cases/tasks/ingest_asset_use_case.py  (MODIFY)
Action:      MODIFY
Effort:      1d
Depends on:  TASK 14, TASK 15, TASK 16
```

**Acceptance criteria:**
- Constructor signature changes to:
  `(idempotency_store, asset_storage: AssetStoragePort, chunk_store: ChunkStorePort, chunker: Callable[[bytes, str], list[Chunk]])`
- `execute()` pipeline:
  1. `idempotency_store.is_processed(asset_id, tenant_id)` → raise `AssetAlreadyProcessedError` if True
  2. `asset_storage.read_bytes(tenant_id, asset_id)` → `content: bytes`
  3. `chunker(content, chunk_strategy)` → `list[Chunk]`
  4. `chunk_store.save_chunks(asset_id, tenant_id, chunks)`
  5. `idempotency_store.mark_processed(asset_id, tenant_id)`
  6. Return `IngestResult(chunk_count=len(chunks), ...)`
- Storage failure propagates without calling chunk_store
- Chunker failure propagates without marking processed

**Test file:** `src/tests/unit/test_ingest_use_case.py` (UPDATE existing)
- Happy path: stub storage returns bytes, stub chunker returns 3 chunks, chunk_store.save_chunks called with all 3
- Duplicate skip: idempotency returns already-processed, no storage or chunker call
- Storage raises `FileNotFoundError` → propagates, chunk_store never called

---

## TASK 19 — Refactor EmbedAssetUseCase — wire ChunkStorePort + EmbeddingPort + VectorStorePort.upsert

```
File:        src/use_cases/tasks/embed_asset_use_case.py  (MODIFY)
Action:      MODIFY
Effort:      1d
Depends on:  TASK 14, TASK 16
```

**Acceptance criteria:**
- Constructor signature changes to:
  `(vector_store: VectorStorePort, chunk_store: ChunkStorePort, embedding_port: EmbeddingPort)`
- `execute()` pipeline:
  1. `vector_store.has_vectors(asset_id, tenant_id)` → raise `AssetAlreadyEmbeddedError` if True
  2. `chunk_store.find_by_asset(asset_id, tenant_id)` → `list[Chunk]`
  3. For each chunk: `embedding_port.embed(chunk.text)` → `list[float]`
  4. `vector_store.upsert(asset_id, tenant_id, embedding, chunk.chunk_id, chunk.text, erp_module=chunk.metadata.get("erp_module"))`
  5. `vector_store.save_vectors(asset_id, tenant_id, len(chunks))`
  6. Return `EmbedResult(vector_count=len(chunks), ...)`
- Empty chunk list → vector_count = 0, `save_vectors(0)` still called
- Embedding failure propagates; no partial upserts (fail fast)

**Test file:** `src/tests/unit/test_embed_use_case.py` (UPDATE existing)
- Happy path: 2 chunks in store → embedder called twice → 2 upserts → save_vectors(2)
- Duplicate skip: `has_vectors` returns True → no chunk_store or embedder call
- Empty chunks: find_by_asset returns [] → vector_count=0
- Embedder raises → propagates, save_vectors never called

---

## TASK 20 — POST /api/assets/upload route

```
File:        src/routes/data.py  (CREATE)
Action:      CREATE
Effort:      0.5d
Depends on:  TASK 15, TASK 17
```

**Acceptance criteria:**
- `POST /api/assets/upload` accepts `multipart/form-data` with `file: UploadFile` + optional `chunk_strategy: str = "sop"`
- Generates `asset_id = str(uuid4())`
- Saves bytes via `AssetStoragePort.save_bytes(tenant_id, asset_id, filename, content)`
- Dispatches ingest job via `JobDispatcherPort.dispatch_ingest(asset_id, tenant_id, chunk_strategy)`
- Returns HTTP 202 with `{asset_id, job_id, filename, size_bytes, chunk_strategy}`
- `tenant_id` sourced from JWT (`request.state.user.tenant_id`)
- Requires valid JWT — `AuthMiddleware` already in stack
- Mounted at `/api/assets` prefix in `main.py`

**Test file:** `src/tests/unit/test_data_route.py`
- Happy path: file uploaded → storage called → job dispatched → 202 with correct body
- Missing file field → 422 Unprocessable Entity
- Storage raises → 500 with structured error body
- Unauthenticated request → 401 (handled by middleware, not tested here)

---

## TASK 21 — Wire all new ports in factory.py + mount data router in main.py

```
File:        src/infrastructure/di/factory.py  (MODIFY)
             src/main.py                        (MODIFY)
Action:      MODIFY
Effort:      0.5d
Depends on:  TASK 15, TASK 16, TASK 17, TASK 18, TASK 19
```

**Acceptance criteria:**
- `build_container()` registers:
  - `AssetStoragePort` → `LocalAssetStorage(base_path=os.environ.get("ASSET_STORAGE_PATH", "/tmp/erp_assets"))`
  - `JobDispatcherPort` → `CeleryJobDispatcher()`
- `build_worker_container()` registers:
  - `ChunkStorePort` → `InMemoryChunkStore()` (no MONGODB_URI) | `MongoChunkStore(collection)` (with MONGODB_URI)
  - `EmbeddingPort` → `NoopEmbeddingProvider()` (no NGROK_BASE_URL) | `NgrokEmbeddingProvider()` (with NGROK_BASE_URL)
  - `IngestAssetUseCase` constructor updated to new signature (asset_storage + chunk_store + chunker)
  - `EmbedAssetUseCase` constructor updated to new signature (chunk_store + embedding_port)
- `ASSET_STORAGE_PATH` added to `.env.example`
- Data router mounted in `main.py`: `app.include_router(data_router, prefix="/api/assets")`
- `container.validate()` still passes — no unbound ports

**Test file:** `src/tests/unit/test_di_factory.py` (UPDATE)
- Worker container has `chunk_store`, `embedding_port` bindings
- API container has `asset_storage`, `job_dispatcher` bindings
- `IngestAssetUseCase.execute()` called end-to-end with stub storage (no file I/O)

---

## Definition of Done (Sprint 7)

```
── HYBRID AGENT ─────────────────────────────────────────────────────────
[ ] asyncio.gather fires SQLAgent and RAGAgent simultaneously
    — verified by test_hybrid_agent.py::test_gather_is_truly_parallel
[ ] Synthesis LLM merges both sources into one merged_answer
    — verified by test_hybrid_agent.py::test_both_succeed_calls_merger_llm
[ ] SQL failure falls back to rag_only=True, no 500 raised
    — verified by test_hybrid_agent.py::test_sql_fails_returns_rag_only_no_exception
[ ] 20 hybrid integration queries all return HTTP 200 with expected sources cited
    — verified by src/tests/integration/test_hybrid_agent.py
[ ] Hybrid path p95 latency < 8 seconds
    — verified by src/tests/performance/test_hybrid_latency.py
[ ] HYBRID_SUCCESS_RATE increments on both agents succeeding
    — verified by test_observability.py
[ ] HYBRID_PARTIAL_RATE increments on partial failure
    — verified by test_observability.py

── INGESTION PIPELINE ───────────────────────────────────────────────────
[ ] POST /api/assets/upload accepts a file and returns {asset_id, job_id} — HTTP 202
[ ] IngestAssetUseCase loads bytes from AssetStoragePort, chunks them, persists via
    ChunkStorePort — verified by unit test with stub ports
[ ] EmbedAssetUseCase loads chunks from ChunkStorePort, calls EmbeddingPort per chunk,
    upserts each into VectorStorePort.upsert — verified by unit test
[ ] VectorRetriever can retrieve a chunk upserted by EmbedAssetUseCase in a single
    in-process test (no external services)
[ ] factory.py container.validate() passes at startup — no unbound port

── GLOBAL ───────────────────────────────────────────────────────────────
[ ] ruff check src/ — zero errors
[ ] mypy src/ --ignore-missing-imports — zero errors
[ ] All Sprint 1–6 tests still pass (no regression)
[ ] sprint-7-done tag pushed, CHANGELOG.md updated
```

---

## Files to Create (summary for Executor)

### Hybrid Agent chain — Tasks 1–13

| # | File | Action | Status |
|---|------|--------|--------|
| 1 | `src/domain/models/__init__.py` | CREATE | ✅ DONE |
| 2 | `src/domain/models/routing_decision.py` | CREATE | ✅ DONE |
| 3 | `src/domain/models/rag_result.py` | CREATE | ✅ DONE |
| 4 | `src/domain/models/sql_result.py` | CREATE | ✅ DONE |
| 5 | `src/domain/models/hybrid_result.py` | CREATE | ✅ DONE |
| 6 | `src/domain/models/scored_chunk.py` | CREATE | ✅ DONE |
| 7 | `src/domain/ports/vector_store_port.py` | MODIFY | ✅ DONE |
| 8 | `src/domain/ports/query_classifier_port.py` | CREATE | ⬜ TODO |
| 9 | `src/domain/ports/llm_port.py` | CREATE | ⬜ TODO |
| 10 | `src/domain/ports/embedding_port.py` | CREATE | ✅ DONE |
| 11 | `src/infrastructure/vector_store/in_memory_vector_store.py` | MODIFY | ✅ DONE |
| 12 | `src/infrastructure/vector_store/mongo_vector_store.py` | MODIFY | ✅ DONE |
| 13 | `src/infrastructure/rag/__init__.py` | CREATE | ✅ DONE |
| 14 | `src/infrastructure/rag/vector_retriever.py` | CREATE | ✅ DONE |
| 15 | `src/infrastructure/rag/embedding_providers.py` | CREATE | ✅ DONE (renamed from noop_embedding_provider.py) |
| 16 | `src/infrastructure/rag/reranker.py` | CREATE | ✅ DONE |
| 17 | `src/infrastructure/rag/context_builder.py` | CREATE | ✅ DONE |
| 18 | `src/infrastructure/nlp/__init__.py` | CREATE | ⬜ TODO |
| 19 | `src/infrastructure/nlp/stub_classifier.py` | CREATE | ⬜ TODO |
| 20 | `src/prompts/__init__.py` | CREATE | ⬜ TODO |
| 21 | `src/prompts/registry.py` | CREATE | ⬜ TODO |
| 22 | `src/prompts/schemas/rag_output.schema.json` | CREATE | ⬜ TODO |
| 23 | `src/prompts/schemas/hybrid_output.schema.json` | CREATE | ⬜ TODO |
| 24 | `src/prompts/versions/rag_answer_v1.yaml` | CREATE | ⬜ TODO |
| 25 | `src/prompts/versions/hybrid_orchestrator_v1.yaml` | CREATE | ⬜ TODO |
| 26 | `src/agents/__init__.py` | CREATE | ⬜ TODO |
| 27 | `src/agents/base_agent.py` | CREATE | ⬜ TODO |
| 28 | `src/agents/sql_agent.py` | CREATE | ⬜ TODO |
| 29 | `src/agents/rag_agent.py` | CREATE | ⬜ TODO |
| 30 | `src/agents/hybrid_agent.py` | CREATE | ⬜ TODO |
| 31 | `src/use_cases/run_rag.py` | CREATE | ⬜ TODO |
| 32 | `src/use_cases/run_hybrid.py` | CREATE | ⬜ TODO |
| 33 | `src/use_cases/route_query.py` | CREATE | ⬜ TODO |
| 34 | `src/infrastructure/di/container.py` | MODIFY | ⬜ TODO |
| 35 | `src/infrastructure/di/factory.py` | MODIFY | ⬜ TODO (TASK 21) |
| 36 | `src/routes/query.py` | CREATE | ⬜ TODO |
| 37 | `src/observability/prometheus_metrics.py` | MODIFY | ⬜ TODO |
| 38 | `src/tests/unit/test_hybrid_domain_models.py` | CREATE | ✅ DONE |
| 39 | `src/tests/unit/test_vector_retriever.py` | CREATE | ✅ DONE |
| 40 | `src/tests/unit/test_rag_infrastructure.py` | CREATE | ✅ DONE |
| 41 | `src/tests/unit/test_prompt_registry.py` | CREATE | ⬜ TODO |
| 42 | `src/tests/unit/test_stub_classifier.py` | CREATE | ⬜ TODO |
| 43 | `src/tests/unit/test_agents.py` | CREATE | ⬜ TODO |
| 44 | `src/tests/unit/test_hybrid_agent.py` | CREATE | ⬜ TODO |
| 45 | `src/tests/unit/test_hybrid_use_cases.py` | CREATE | ⬜ TODO |
| 46 | `src/tests/fixtures/hybrid_test_queries.json` | CREATE | ⬜ TODO |
| 47 | `src/tests/integration/test_hybrid_agent.py` | CREATE | ⬜ TODO |
| 48 | `src/tests/performance/test_hybrid_latency.py` | CREATE | ⬜ TODO |

### Ingestion Pipeline — Tasks 14–21

| # | File | Action | Status |
|---|------|--------|--------|
| 49 | `src/domain/chunk.py` | MODIFY (add chunk_id) | ⬜ TODO |
| 50 | `src/domain/ports/asset_storage_port.py` | CREATE | ✅ DONE (uncommitted) |
| 51 | `src/domain/ports/chunk_store_port.py` | CREATE | ✅ DONE (uncommitted) |
| 52 | `src/domain/ports/job_dispatcher_port.py` | CREATE | ✅ DONE (uncommitted) |
| 53 | `src/infrastructure/storage/__init__.py` | CREATE | ⬜ TODO |
| 54 | `src/infrastructure/storage/local_asset_storage.py` | CREATE | ⬜ TODO |
| 55 | `src/infrastructure/persistence/__init__.py` | CREATE | ⬜ TODO |
| 56 | `src/infrastructure/persistence/chunk_store.py` | CREATE | ⬜ TODO |
| 57 | `src/infrastructure/workers/celery_job_dispatcher.py` | CREATE | ⬜ TODO |
| 58 | `src/use_cases/tasks/ingest_asset_use_case.py` | MODIFY | ⬜ TODO |
| 59 | `src/use_cases/tasks/embed_asset_use_case.py` | MODIFY | ⬜ TODO |
| 60 | `src/routes/data.py` | CREATE | ⬜ TODO |
| 61 | `src/tests/unit/test_local_asset_storage.py` | CREATE | ⬜ TODO |
| 62 | `src/tests/unit/test_chunk_store.py` | CREATE | ⬜ TODO |
| 63 | `src/tests/unit/test_celery_job_dispatcher.py` | CREATE | ⬜ TODO |
| 64 | `src/tests/unit/test_ingest_use_case.py` | MODIFY | ⬜ TODO |
| 65 | `src/tests/unit/test_embed_use_case.py` | MODIFY | ⬜ TODO |
| 66 | `src/tests/unit/test_data_route.py` | CREATE | ⬜ TODO |

**MODIFY only (extend, do not replace):**
- `src/domain/ports/vector_store_port.py` ✅
- `src/infrastructure/vector_store/in_memory_vector_store.py` ✅
- `src/infrastructure/vector_store/mongo_vector_store.py` ✅
- `src/infrastructure/di/container.py` (TASK 10 + TASK 21)
- `src/infrastructure/di/factory.py` (TASK 10 + TASK 21)
- `src/observability/prometheus_metrics.py` (TASK 11)
- `src/tests/unit/test_observability.py` (TASK 11)
- `src/tests/unit/test_di_factory.py` (TASK 10 + TASK 21)
- `src/tests/unit/test_vector_store_port.py` ✅
- `src/tests/unit/test_ingestion_ports.py` ✅ (uncommitted)

---

**READY FOR EXECUTOR: YES**
_Tasks 1–4 done. Ingestion pipeline (Tasks 14–21) and Hybrid Agent chain (Tasks 5–13) are both unblocked and can proceed independently. Start with Tasks 14–17 (all parallel) then 18–21._
