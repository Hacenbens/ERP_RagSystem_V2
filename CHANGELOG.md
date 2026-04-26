# Changelog

All notable changes to this project are documented here.
Format follows [Conventional Commits](https://www.conventionalcommits.org/).

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
