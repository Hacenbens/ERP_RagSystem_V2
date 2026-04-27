# Changelog

All notable changes to this project are documented here.
Format follows [Conventional Commits](https://www.conventionalcommits.org/).

---

## [sprint-9-partial] — 2026-04-27

### Added
- feat(vector-store): MilvusVectorStore — FLAT/COSINE collection, upsert idempotency (delete-before-insert), tenant isolation via filter expressions, erp_module filter support, Milvus Lite (.db) and full Milvus server URI support
- feat(di): `_select_vector_store()` factory helper — env-driven selection of MilvusVectorStore (MILVUS_URI set) or InMemoryVectorStore fallback; wired into both build_query_chain() and build_worker_container()
- feat(di): remove broken MongoVectorStore branch (NotImplementedError on upsert) from worker container; embed tasks now route through Milvus in production
- test(vector-store): 25 unit tests for MilvusVectorStore (upsert, search, tenant isolation, idempotency tracking, content truncation, port compliance)
- test(vector-store): 20 integration tests against real Milvus Lite .db file — full pipeline, tenant isolation (security gate), erp_module filter, upsert idempotency
- test(di): 2 factory tests verifying env-driven vector store selection

### Fixed
- fix(di): removed MongoVectorStore.upsert NotImplementedError that silently broke all embed tasks in production when MONGODB_URI was set

---

## [sprint-8-done] — 2026-04-26

### Added
- feat(generation): ModelSelectorPort + DegradedModePort ABCs and LLMUnavailableError domain exception
- feat(generation): GeminiLLMClient (gemini-2.5-flash-lite free tier) + vLLMLLMClient (httpx, OpenAI-compatible)
- feat(generation): CircuitBreaker (per-provider failure state machine, HALF-OPEN after 60s)
- feat(generation): ModelSelector with ordered fallback (Gemini → vLLM) and circuit-breaker integration
- feat(generation): DegradedModeService with per-query-hash answer cache and degraded JSON sentinel
- feat(agents): QueryClassifierAgent — LLM-backed classify() with classifier_v1 prompt (10/10 live accuracy)
- feat(prompts): classifier_v1.yaml (4-intent ERP classifier with few-shots) + classifier_output.schema.json
- feat(prompts): sql_generator_v1.yaml (mandatory tenant_id filter) + sql_generator_output.schema.json
- feat(prompts): evaluator_v1.yaml (LLM-as-judge, 5-axis scoring) + evaluator_output.schema.json
- feat(observability): MetricsCollector per-request accumulator with idempotent flush() to Prometheus
- feat(observability): QUERY_STAGE_LATENCY_MS histogram + TOKENS_USED counter
- feat(notebooks): kaggle_llm_server.ipynb — vLLM + embedding server startup guide for Kaggle GPU

### Tested
- test(generation): 45 tests for ModelSelectorPort, DegradedModePort, domain exceptions
- test(generation): 50 tests for GeminiLLMClient and vLLMLLMClient
- test(generation): 27 tests for ModelSelector fallback and CircuitBreaker (timing via mocked monotonic)
- test(generation): 27 integration tests for DegradedModeService (cache hit/miss, Prometheus, logging)
- test(agents): 12 tests for QueryClassifierAgent (all 4 intents, error paths, module mapping)
- test(prompts): 17 tests for sql_generator and evaluator prompts (schema validation)
- test(observability): 23 tests for MetricsCollector (idempotency, all stages, tokens, degraded)
- test(notebooks): 15 tests for notebook structure and code cell syntax validation
- Full suite: 1407 passed, 0 failures (target was ≥ 1192)

---

## [sprint-7-done] — 2026-04-26

### Added
- feat(domain): Chunk.chunk_id stable field; AssetStoragePort, ChunkStorePort, JobDispatcherPort ABCs
- feat(storage): LocalAssetStorage implementing AssetStoragePort
- feat(persistence): InMemoryChunkStore and MongoChunkStore implementing ChunkStorePort
- feat(workers): CeleryJobDispatcher implementing JobDispatcherPort
- feat(hybrid-agent): LLMPort, BaseAgent, RAGAgent, SQLAgent, HybridAgent with asyncio.gather and partial failure handling
- feat(hybrid-agent): VectorRetriever, IdentityReranker, ContextBuilder, PromptRegistry, StubClassifier
- feat(hybrid-agent): RunRAGUseCase, RunSQLUseCase, RunHybridUseCase, RouteQueryUseCase
- feat(hybrid-agent): POST /api/v1/query route wired through DI container
- feat(hybrid-agent): POST /api/assets/upload route with storage and job dispatch
- feat(observability): HYBRID_PARTIAL_RATE counter for partial RAG+SQL failures
- feat(rag): NgrokEmbeddingProvider with batch texts API; InMemoryVectorStore upsert + cosine search

### Refactored
- refactor(ingest): IngestAssetUseCase wired with AssetStoragePort and ChunkStorePort; chunker signature → (bytes, str) → list[Chunk]
- refactor(embed): EmbedAssetUseCase wired with ChunkStorePort and EmbeddingPort; removed chunker/embedder constructor args

### Tested
- test(hybrid-agent): 18 unit tests — VectorStorePort extensions, VectorRetriever
- test(hybrid-agent): unit tests — HybridAgent, RAGAgent, SQLAgent partial failure, asyncio.gather
- test(hybrid-agent): 20-query end-to-end integration test for hybrid pipeline via POST /api/v1/query
- test(performance): hybrid p95 latency test — 10 queries, p95 ≤ 8000 ms, observed ~13 ms
- test(workers): updated 28 + 32 + 74 integration tests for refactored IngestAssetUseCase and EmbedAssetUseCase signatures
- fix(tests): added build_query_chain to middleware, module-guard, and middleware-order test app factories
- Total Sprint 7 tests: 1192 passing suite-wide, 0 failures

---

## [sprint-6-done] — 2026-04-22

### Added
- feat(domain): Chunk, TableElement, EmbedResult dataclasses; VectorStorePort, IdempotencyStorePort, DeadLetterRepositoryPort
- feat(workers): Celery app (Redis broker/backend), ingest_asset task with retry + dead-letter + idempotency
- feat(chunkers): BaseChunker (LangChain RecursiveCharacterTextSplitter), SOPChunker, BPMNChunker, TaxCircularChunker (Unstructured.io layout analysis — separates text from tables, embeds table summaries with full raw table in metadata), ChunkerFactory
- feat(workers): embed_asset Celery task — chunk-first pipeline (list[Chunk] → embedder with metadata), idempotency via VectorStorePort, retry/dead-letter mirrors ingest pattern
- feat(workers): InMemoryVectorStore and MongoVectorStore (embedded_assets collection, upsert with vector_count + embedded_at)
- feat(use-cases): EmbedAssetUseCase — idempotency check, chunker → embedder handoff preserving per-chunk metadata
- feat(di): build_worker_container wires ingest + embed use cases; WORKER_REQUIRED_PORTS includes embed_use_case
- feat(workers): GET /admin/jobs/{job_id} wired to real Celery AsyncResult (PENDING/STARTED/SUCCESS/FAILURE/RETRY/REVOKED)
- feat(observability): EMBED_TASKS_DISPATCHED, EMBED_TASKS_FAILED, EMBED_TASK_DURATION Prometheus metrics

### Tested
- test(workers): 28 unit tests — domain models, InMemory repos, IngestAssetUseCase
- test(chunkers): 78 unit tests — TaxCircularChunker (HTML + plain-text paths), helpers, TableElement
- test(workers): 56 integration tests — ingest_asset Celery eager-mode (retry chain, dead-letter, idempotency, metrics)
- test(workers): 78 unit + integration tests — EmbedResult, InMemoryVectorStore, MongoVectorStore (mocked), EmbedAssetUseCase, embed_asset task
- test(workers): 25 unit tests — GET /admin/jobs/{id} all Celery states + response contract
- test(workers): 44 integration tests — /metrics endpoint health, all Sprint 6 metric families in REGISTRY and text, counters verified through real eager dispatches
- Total Sprint 6 tests: 309 new tests — 899 passing suite-wide, 0 failures

### Infrastructure
- chore(deps): requirements.txt frozen with pymongo==4.17.0, unstructured==0.22.22, pymilvus==2.5.18
- refactor(workers): relocated celery_app and ingest_task to src/infrastructure/workers/
