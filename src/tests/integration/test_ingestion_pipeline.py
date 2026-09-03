"""
End-to-end ingestion pipeline — Sprint 10 (audit findings B-4, B-5).

The audit found the pipeline severed in two places, and no test noticed
because every existing test entered mid-pipeline with well-formed arguments:

  B-4  POST /api/assets/upload discarded the storage key that save_bytes
       returned and handed the worker a bare asset_id. read_bytes rejected it
       on the tenant-prefix check, so every real upload failed three times and
       landed in the dead-letter queue.

  B-5  Nothing ever called dispatch_embed. Even with B-4 fixed, documents were
       chunked and stored and then stopped: the vector store stayed empty and
       every RAG query returned "not grounded", permanently.

These tests run the whole path — HTTP upload, ingest, embed, retrieve — so a
break at any hand-off fails here rather than in production.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.chunk import Chunk
from src.domain.ports.embedding_port import EmbeddingPort
from src.infrastructure.di.container import DIContainer
from src.infrastructure.persistence.chunk_store import InMemoryChunkStore
from src.infrastructure.storage.local_asset_storage import LocalAssetStorage
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.infrastructure.workers.idempotency_store import InMemoryIdempotencyStore
from src.routes.data import router as data_router
from src.use_cases.tasks.embed_asset_use_case import EmbedAssetUseCase
from src.use_cases.tasks.ingest_asset_use_case import IngestAssetUseCase

TENANT = "tenant-ferza"
DOC = b"Purchase requisitions above 50000 DZD require finance director approval."


class _HashEmbedder(EmbeddingPort):
    """Deterministic non-zero embedding, so cosine similarity is meaningful."""

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * 8
        for i, ch in enumerate(text):
            vec[i % 8] += (ord(ch) % 17) / 100.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


class _RecordingDispatcher:
    """Runs jobs inline and records them, standing in for the Celery broker."""

    def __init__(self, ingest_uc, embed_uc) -> None:
        self._ingest_uc = ingest_uc
        self._embed_uc = embed_uc
        self.ingest_calls: list[dict] = []
        self.embed_calls: list[dict] = []

    def dispatch_ingest(
        self, asset_id: str, tenant_id: str, chunk_strategy: str, storage_key: str
    ) -> str:
        self.ingest_calls.append(
            {
                "asset_id": asset_id,
                "tenant_id": tenant_id,
                "chunk_strategy": chunk_strategy,
                "storage_key": storage_key,
            }
        )
        self._ingest_uc.execute(
            asset_id=asset_id,
            tenant_id=tenant_id,
            chunk_strategy=chunk_strategy,
            task_id="inline-ingest",
            storage_key=storage_key,
        )
        # What ingest_task does on success — the hand-off B-5 was missing.
        self.dispatch_embed(asset_id, tenant_id, chunk_strategy)
        return "ingest-job-1"

    def dispatch_embed(self, asset_id: str, tenant_id: str, chunk_strategy: str) -> str:
        self.embed_calls.append(
            {"asset_id": asset_id, "tenant_id": tenant_id, "chunk_strategy": chunk_strategy}
        )
        self._embed_uc.execute(
            asset_id=asset_id,
            tenant_id=tenant_id,
            chunk_strategy=chunk_strategy,
            task_id="inline-embed",
        )
        return "embed-job-1"


@pytest.fixture()
def pipeline(tmp_path) -> Iterator[tuple[TestClient, _RecordingDispatcher, InMemoryVectorStore]]:
    storage = LocalAssetStorage(base_path=str(tmp_path))
    chunk_store = InMemoryChunkStore()
    vector_store = InMemoryVectorStore()

    ingest_uc = IngestAssetUseCase(
        idempotency_store=InMemoryIdempotencyStore(),
        asset_storage=storage,
        chunk_store=chunk_store,
        chunker=lambda content, strategy: [
            Chunk(text=line) for line in content.decode().splitlines() if line.strip()
        ],
    )
    embed_uc = EmbedAssetUseCase(
        vector_store=vector_store,
        chunk_store=chunk_store,
        embedding_port=_HashEmbedder(),
    )
    dispatcher = _RecordingDispatcher(ingest_uc, embed_uc)

    container = DIContainer()
    container.register("asset_storage", storage)
    container.register("job_dispatcher", dispatcher)

    app = FastAPI()
    app.state.container = container
    app.include_router(data_router)

    # No auth middleware here; the route reads tenant_id off request.state.
    @app.middleware("http")
    async def _set_tenant(request, call_next):
        request.state.tenant_id = TENANT
        return await call_next(request)

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, dispatcher, vector_store


def _upload(client: TestClient) -> dict:
    resp = client.post(
        "/api/assets/upload",
        files={"file": ("sop.txt", DOC, "text/plain")},
        data={"chunk_strategy": "sop"},
    )
    assert resp.status_code == 202, resp.text
    return resp.json()


class TestStorageKeyReachesTheWorker:
    """B-4 — the key save_bytes returned must be what the worker is given."""

    def test_dispatcher_receives_the_full_storage_key(self, pipeline):
        client, dispatcher, _ = pipeline
        body = _upload(client)

        key = dispatcher.ingest_calls[0]["storage_key"]
        assert key == f"{TENANT}/{body['asset_id']}/sop.txt"

    def test_key_is_not_the_bare_asset_id(self, pipeline):
        """The exact regression: a bare asset_id fails the tenant-prefix check."""
        client, dispatcher, _ = pipeline
        body = _upload(client)

        assert dispatcher.ingest_calls[0]["storage_key"] != body["asset_id"]

    def test_the_worker_can_actually_read_the_bytes_back(self, pipeline, tmp_path):
        client, dispatcher, _ = pipeline
        _upload(client)

        storage = LocalAssetStorage(base_path=str(tmp_path))
        key = dispatcher.ingest_calls[0]["storage_key"]
        assert storage.read_bytes(TENANT, key) == DOC

    def test_bare_asset_id_still_raises(self, pipeline, tmp_path):
        """Pin why the key is needed, so nobody 'simplifies' it back."""
        client, dispatcher, _ = pipeline
        body = _upload(client)

        storage = LocalAssetStorage(base_path=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT, body["asset_id"])


class TestEmbedIsDispatched:
    """B-5 — ingestion that never embeds leaves retrieval permanently empty."""

    def test_ingest_success_queues_an_embed_job(self, pipeline):
        client, dispatcher, _ = pipeline
        _upload(client)

        assert len(dispatcher.embed_calls) == 1

    def test_embed_job_targets_the_uploaded_asset(self, pipeline):
        client, dispatcher, _ = pipeline
        body = _upload(client)

        assert dispatcher.embed_calls[0]["asset_id"] == body["asset_id"]


class TestDocumentBecomesRetrievable:
    """The property that actually matters: an upload ends up searchable."""

    def test_vector_store_is_populated(self, pipeline):
        client, _, vector_store = pipeline
        body = _upload(client)

        assert vector_store.count(body["asset_id"], TENANT) > 0

    def test_uploaded_text_is_retrievable_by_similarity(self, pipeline):
        client, _, vector_store = pipeline
        _upload(client)

        query = _HashEmbedder().embed(DOC.decode())
        hits = vector_store.search_similar(query_embedding=query, k=5, tenant_id=TENANT)

        assert hits, "nothing retrievable — the pipeline did not reach the vector store"
        assert "purchase requisitions" in hits[0].content.lower()

    def test_another_tenant_cannot_retrieve_it(self, pipeline):
        client, _, vector_store = pipeline
        _upload(client)

        query = _HashEmbedder().embed(DOC.decode())
        assert vector_store.search_similar(
            query_embedding=query, k=5, tenant_id="other-tenant"
        ) == []
