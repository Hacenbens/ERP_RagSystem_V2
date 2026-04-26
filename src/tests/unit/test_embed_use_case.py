"""
Unit tests — Sprint 7 Task 19 (refactored from Sprint 6 Task 4)
Covers: EmbedResult, InMemoryVectorStore, MongoVectorStore (mocked), EmbedAssetUseCase (new signature)

All tests are pure in-memory — no Celery, no MongoDB, no I/O.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.domain.chunk import Chunk
from src.domain.embed_result import EmbedResult
from src.domain.ports.embedding_port import EmbeddingPort
from src.infrastructure.persistence.chunk_store import InMemoryChunkStore
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.infrastructure.vector_store.mongo_vector_store import MongoVectorStore
from src.use_cases.tasks.embed_asset_use_case import (
    AssetAlreadyEmbeddedError,
    EmbedAssetUseCase,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ASSET_ID = "asset-embed-001"
TENANT_ID = "tenant-ferza"
OTHER_TENANT = "tenant-acme"
TASK_ID = "task-embed-xyz"
STRATEGY = "sop"

_CHUNKS = [
    Chunk(text="Article 1 — scope", metadata={"section": "scope", "chunk_type": "text"}),
    Chunk(text="Article 2 — definitions", metadata={"section": "definitions", "chunk_type": "text"}),
    Chunk(text="[Table] rates — 5 rows", metadata={"chunk_type": "table_summary", "table_raw": "..."}),
]


class _NoopEmbedder(EmbeddingPort):
    """Zero-vector embedder for tests — no external calls."""
    def embed(self, text: str) -> list[float]:
        return [0.0] * 4


class _FailingEmbedder(EmbeddingPort):
    def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedder simulated failure")


# ---------------------------------------------------------------------------
# EmbedResult domain model
# ---------------------------------------------------------------------------

class TestEmbedResult:
    def test_fields_stored_correctly(self):
        result = EmbedResult(
            asset_id=ASSET_ID,
            tenant_id=TENANT_ID,
            vector_count=7,
            chunk_strategy=STRATEGY,
            duration_ms=55.3,
            task_id=TASK_ID,
        )
        assert result.asset_id == ASSET_ID
        assert result.tenant_id == TENANT_ID
        assert result.vector_count == 7
        assert result.chunk_strategy == STRATEGY
        assert result.duration_ms == 55.3
        assert result.task_id == TASK_ID

    def test_vector_count_zero_is_valid(self):
        result = EmbedResult(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            vector_count=0, chunk_strategy=STRATEGY,
            duration_ms=0.0, task_id=TASK_ID,
        )
        assert result.vector_count == 0

    def test_two_results_with_same_data_are_equal(self):
        r1 = EmbedResult(ASSET_ID, TENANT_ID, 3, STRATEGY, 10.0, TASK_ID)
        r2 = EmbedResult(ASSET_ID, TENANT_ID, 3, STRATEGY, 10.0, TASK_ID)
        assert r1 == r2

    def test_different_vector_counts_are_not_equal(self):
        r1 = EmbedResult(ASSET_ID, TENANT_ID, 3, STRATEGY, 10.0, TASK_ID)
        r2 = EmbedResult(ASSET_ID, TENANT_ID, 5, STRATEGY, 10.0, TASK_ID)
        assert r1 != r2


# ---------------------------------------------------------------------------
# InMemoryVectorStore
# ---------------------------------------------------------------------------

class TestInMemoryVectorStore:
    def test_new_asset_has_no_vectors(self):
        store = InMemoryVectorStore()
        assert store.has_vectors(ASSET_ID, TENANT_ID) is False

    def test_save_vectors_marks_asset_as_having_vectors(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 5)
        assert store.has_vectors(ASSET_ID, TENANT_ID) is True

    def test_count_returns_zero_before_save(self):
        store = InMemoryVectorStore()
        assert store.count(ASSET_ID, TENANT_ID) == 0

    def test_count_returns_saved_vector_count(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 12)
        assert store.count(ASSET_ID, TENANT_ID) == 12

    def test_save_vectors_overwrites_previous_count(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 5)
        store.save_vectors(ASSET_ID, TENANT_ID, 20)
        assert store.count(ASSET_ID, TENANT_ID) == 20

    def test_different_tenants_same_asset_id_are_isolated(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 8)
        assert store.has_vectors(ASSET_ID, OTHER_TENANT) is False
        assert store.count(ASSET_ID, OTHER_TENANT) == 0

    def test_different_assets_same_tenant_are_isolated(self):
        store = InMemoryVectorStore()
        store.save_vectors("asset-A", TENANT_ID, 3)
        assert store.has_vectors("asset-B", TENANT_ID) is False

    def test_clear_removes_all_entries(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 5)
        store.save_vectors("asset-B", TENANT_ID, 3)
        store.clear()
        assert store.has_vectors(ASSET_ID, TENANT_ID) is False
        assert store.count(ASSET_ID, TENANT_ID) == 0

    def test_save_vectors_zero_count_is_recorded(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 0)
        assert store.has_vectors(ASSET_ID, TENANT_ID) is True
        assert store.count(ASSET_ID, TENANT_ID) == 0

    def test_multiple_assets_tracked_independently(self):
        store = InMemoryVectorStore()
        store.save_vectors("asset-1", TENANT_ID, 2)
        store.save_vectors("asset-2", TENANT_ID, 9)
        assert store.count("asset-1", TENANT_ID) == 2
        assert store.count("asset-2", TENANT_ID) == 9


# ---------------------------------------------------------------------------
# MongoVectorStore — mocked collection
# ---------------------------------------------------------------------------

class TestMongoVectorStore:
    def _make_store(self) -> tuple[MongoVectorStore, MagicMock]:
        collection = MagicMock()
        return MongoVectorStore(collection), collection

    def test_has_vectors_returns_true_when_document_exists(self):
        store, col = self._make_store()
        col.count_documents.return_value = 1
        assert store.has_vectors(ASSET_ID, TENANT_ID) is True
        col.count_documents.assert_called_once_with(
            {"asset_id": ASSET_ID, "tenant_id": TENANT_ID}, limit=1
        )

    def test_has_vectors_returns_false_when_no_document(self):
        store, col = self._make_store()
        col.count_documents.return_value = 0
        assert store.has_vectors(ASSET_ID, TENANT_ID) is False

    def test_save_vectors_calls_update_one_with_upsert(self):
        store, col = self._make_store()
        store.save_vectors(ASSET_ID, TENANT_ID, 7)
        col.update_one.assert_called_once()
        call_kwargs = col.update_one.call_args
        assert call_kwargs.kwargs["upsert"] is True

    def test_save_vectors_filter_matches_asset_and_tenant(self):
        store, col = self._make_store()
        store.save_vectors(ASSET_ID, TENANT_ID, 7)
        filter_doc = col.update_one.call_args.args[0]
        assert filter_doc == {"asset_id": ASSET_ID, "tenant_id": TENANT_ID}

    def test_save_vectors_sets_correct_vector_count(self):
        store, col = self._make_store()
        store.save_vectors(ASSET_ID, TENANT_ID, 7)
        update_doc = col.update_one.call_args.args[1]
        assert update_doc["$set"]["vector_count"] == 7

    def test_save_vectors_sets_embedded_at_timestamp(self):
        store, col = self._make_store()
        store.save_vectors(ASSET_ID, TENANT_ID, 3)
        update_doc = col.update_one.call_args.args[1]
        assert "embedded_at" in update_doc["$set"]
        assert "T" in update_doc["$set"]["embedded_at"]

    def test_count_returns_vector_count_from_document(self):
        store, col = self._make_store()
        col.find_one.return_value = {"vector_count": 14}
        assert store.count(ASSET_ID, TENANT_ID) == 14

    def test_count_returns_zero_when_no_document(self):
        store, col = self._make_store()
        col.find_one.return_value = None
        assert store.count(ASSET_ID, TENANT_ID) == 0

    def test_count_queries_correct_fields(self):
        store, col = self._make_store()
        col.find_one.return_value = {"vector_count": 5}
        store.count(ASSET_ID, TENANT_ID)
        col.find_one.assert_called_once_with(
            {"asset_id": ASSET_ID, "tenant_id": TENANT_ID},
            {"vector_count": 1},
        )


# ---------------------------------------------------------------------------
# EmbedAssetUseCase — Sprint 7 refactored signature
# ---------------------------------------------------------------------------

class TestEmbedAssetUseCase:
    def _make_use_case(
        self,
        chunks: list[Chunk] | None = None,
        embedder: EmbeddingPort | None = None,
        vector_store: InMemoryVectorStore | None = None,
    ) -> tuple[EmbedAssetUseCase, InMemoryVectorStore, InMemoryChunkStore]:
        vs = vector_store or InMemoryVectorStore()
        cs = InMemoryChunkStore()
        if chunks is not None:
            cs.save_chunks(ASSET_ID, TENANT_ID, chunks)
        ep = embedder or _NoopEmbedder()
        uc = EmbedAssetUseCase(vector_store=vs, chunk_store=cs, embedding_port=ep)
        return uc, vs, cs

    # --- Happy path --------------------------------------------------------

    def test_happy_path_returns_embed_result(self):
        uc, _, _ = self._make_use_case(chunks=list(_CHUNKS))
        result = uc.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert isinstance(result, EmbedResult)

    def test_happy_path_vector_count_equals_chunk_count(self):
        uc, _, _ = self._make_use_case(chunks=list(_CHUNKS))
        result = uc.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.vector_count == len(_CHUNKS)

    def test_happy_path_vectors_upserted_per_chunk(self):
        uc, vs, _ = self._make_use_case(chunks=list(_CHUNKS))
        uc.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert vs.count(ASSET_ID, TENANT_ID) == len(_CHUNKS)

    def test_happy_path_save_vectors_called(self):
        uc, vs, _ = self._make_use_case(chunks=list(_CHUNKS))
        uc.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert vs.has_vectors(ASSET_ID, TENANT_ID) is True

    def test_happy_path_duration_ms_is_non_negative(self):
        uc, _, _ = self._make_use_case(chunks=list(_CHUNKS))
        result = uc.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.duration_ms >= 0.0

    def test_embedding_port_called_once_per_chunk(self):
        call_texts: list[str] = []

        class RecordingEmbedder(EmbeddingPort):
            def embed(self, text: str) -> list[float]:
                call_texts.append(text)
                return [0.0]

        uc, _, _ = self._make_use_case(
            chunks=list(_CHUNKS), embedder=RecordingEmbedder()
        )
        uc.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert call_texts == [c.text for c in _CHUNKS]

    # --- Empty chunks ---------------------------------------------------

    def test_empty_chunk_list_returns_zero_vector_count(self):
        uc, vs, _ = self._make_use_case(chunks=[])
        result = uc.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.vector_count == 0
        assert vs.count(ASSET_ID, TENANT_ID) == 0

    # --- Idempotency guard ---------------------------------------------

    def test_already_embedded_raises(self):
        vs = InMemoryVectorStore()
        vs.save_vectors(ASSET_ID, TENANT_ID, 5)
        uc, _, _ = self._make_use_case(chunks=[], vector_store=vs)
        with pytest.raises(AssetAlreadyEmbeddedError):
            uc.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_already_embedded_does_not_call_embedder(self):
        vs = InMemoryVectorStore()
        vs.save_vectors(ASSET_ID, TENANT_ID, 5)
        embedder_called = [False]

        class SentinelEmbedder(EmbeddingPort):
            def embed(self, text: str) -> list[float]:
                embedder_called[0] = True
                return [0.0]

        uc, _, _ = self._make_use_case(chunks=[], embedder=SentinelEmbedder(), vector_store=vs)
        with pytest.raises(AssetAlreadyEmbeddedError):
            uc.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        assert embedder_called[0] is False

    def test_different_tenant_same_asset_not_blocked(self):
        vs = InMemoryVectorStore()
        vs.save_vectors(ASSET_ID, TENANT_ID, 5)
        cs = InMemoryChunkStore()
        cs.save_chunks(ASSET_ID, OTHER_TENANT, list(_CHUNKS))
        uc = EmbedAssetUseCase(vector_store=vs, chunk_store=cs, embedding_port=_NoopEmbedder())
        result = uc.execute(
            asset_id=ASSET_ID, tenant_id=OTHER_TENANT,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.tenant_id == OTHER_TENANT

    # --- Embedder failure ---------------------------------------------------

    def test_embedder_failure_propagates(self):
        uc, _, _ = self._make_use_case(
            chunks=list(_CHUNKS), embedder=_FailingEmbedder()
        )
        with pytest.raises(RuntimeError, match="embedder simulated failure"):
            uc.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_embedder_failure_does_not_save_vectors(self):
        uc, vs, _ = self._make_use_case(
            chunks=list(_CHUNKS), embedder=_FailingEmbedder()
        )
        with pytest.raises(RuntimeError):
            uc.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        assert vs.has_vectors(ASSET_ID, TENANT_ID) is False

    # --- Multi-asset isolation -------------------------------------------

    def test_two_different_assets_embedded_independently(self):
        vs = InMemoryVectorStore()
        cs = InMemoryChunkStore()
        cs.save_chunks("asset-X", TENANT_ID, [Chunk(text="x")])
        cs.save_chunks("asset-Y", TENANT_ID, [Chunk(text="y")])
        uc = EmbedAssetUseCase(vector_store=vs, chunk_store=cs, embedding_port=_NoopEmbedder())
        uc.execute(asset_id="asset-X", tenant_id=TENANT_ID, chunk_strategy=STRATEGY, task_id="t1")
        uc.execute(asset_id="asset-Y", tenant_id=TENANT_ID, chunk_strategy=STRATEGY, task_id="t2")
        assert vs.has_vectors("asset-X", TENANT_ID) is True
        assert vs.has_vectors("asset-Y", TENANT_ID) is True
