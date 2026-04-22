# Changelog

All notable changes to this project are documented here.
Format follows [Conventional Commits](https://www.conventionalcommits.org/).

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
