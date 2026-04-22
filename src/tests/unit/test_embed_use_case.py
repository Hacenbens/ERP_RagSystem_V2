"""
Unit tests — Sprint 6 Task 4
Covers: EmbedResult, InMemoryVectorStore, MongoVectorStore (mocked), EmbedAssetUseCase

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


def _success_chunker(asset_id: str, tenant_id: str, strategy: str) -> list[Chunk]:
    return list(_CHUNKS)


def _failing_chunker(asset_id: str, tenant_id: str, strategy: str) -> list[Chunk]:
    raise RuntimeError("chunker simulated failure")


def _success_embedder(chunks: list[Chunk], asset_id: str, tenant_id: str) -> int:
    return len(chunks)


def _failing_embedder(chunks: list[Chunk], asset_id: str, tenant_id: str) -> int:
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
# EmbedAssetUseCase
# ---------------------------------------------------------------------------

class TestEmbedAssetUseCase:
    def _make_use_case(
        self,
        chunker=_success_chunker,
        embedder=_success_embedder,
        vector_store: InMemoryVectorStore | None = None,
    ) -> tuple[EmbedAssetUseCase, InMemoryVectorStore]:
        store = vector_store or InMemoryVectorStore()
        use_case = EmbedAssetUseCase(
            vector_store=store,
            chunker=chunker,
            embedder=embedder,
        )
        return use_case, store

    # --- Happy path --------------------------------------------------------

    def test_happy_path_returns_embed_result(self):
        use_case, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert isinstance(result, EmbedResult)

    def test_happy_path_result_has_correct_asset_and_tenant(self):
        use_case, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.asset_id == ASSET_ID
        assert result.tenant_id == TENANT_ID

    def test_happy_path_vector_count_equals_chunk_count(self):
        use_case, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.vector_count == len(_CHUNKS)

    def test_happy_path_chunk_strategy_preserved_in_result(self):
        use_case, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy="bpmn", task_id=TASK_ID,
        )
        assert result.chunk_strategy == "bpmn"

    def test_happy_path_task_id_preserved_in_result(self):
        use_case, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.task_id == TASK_ID

    def test_happy_path_duration_ms_is_non_negative(self):
        use_case, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.duration_ms >= 0.0

    def test_happy_path_vectors_saved_in_store(self):
        use_case, store = self._make_use_case()
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert store.has_vectors(ASSET_ID, TENANT_ID) is True
        assert store.count(ASSET_ID, TENANT_ID) == len(_CHUNKS)

    # --- Chunker → embedder pipeline contract -----------------------------

    def test_chunker_receives_correct_arguments(self):
        received: list[tuple] = []

        def recording_chunker(asset_id: str, tenant_id: str, strategy: str) -> list[Chunk]:
            received.append((asset_id, tenant_id, strategy))
            return [Chunk(text="x", metadata={})]

        use_case, _ = self._make_use_case(chunker=recording_chunker)
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy="tax_circular", task_id=TASK_ID,
        )
        assert received == [(ASSET_ID, TENANT_ID, "tax_circular")]

    def test_embedder_receives_chunks_from_chunker(self):
        """The chunks produced by the chunker must be passed verbatim to the embedder."""
        expected_chunks = [
            Chunk(text="section A", metadata={"section": "A"}),
            Chunk(text="section B", metadata={"section": "B"}),
        ]
        received_chunks: list[list[Chunk]] = []

        def recording_embedder(chunks: list[Chunk], asset_id: str, tenant_id: str) -> int:
            received_chunks.append(chunks)
            return len(chunks)

        use_case, _ = self._make_use_case(
            chunker=lambda a, t, s: expected_chunks,
            embedder=recording_embedder,
        )
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert received_chunks[0] == expected_chunks

    def test_embedder_receives_asset_id_and_tenant_id(self):
        received_context: list[tuple] = []

        def recording_embedder(chunks: list[Chunk], asset_id: str, tenant_id: str) -> int:
            received_context.append((asset_id, tenant_id))
            return 1

        use_case, _ = self._make_use_case(
            chunker=lambda a, t, s: [Chunk(text="t", metadata={})],
            embedder=recording_embedder,
        )
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert received_context == [(ASSET_ID, TENANT_ID)]

    def test_embedder_called_once_not_per_chunk(self):
        """EmbedAssetUseCase calls embedder once with all chunks — not once per chunk."""
        call_count = [0]

        def counting_embedder(chunks: list[Chunk], asset_id: str, tenant_id: str) -> int:
            call_count[0] += 1
            return len(chunks)

        use_case, _ = self._make_use_case(embedder=counting_embedder)
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert call_count[0] == 1

    def test_chunk_metadata_passed_through_to_embedder(self):
        """Chunk.metadata must survive the chunker → embedder handoff unchanged."""
        rich_meta = {"section": "art. 3", "chunk_type": "table_summary", "table_raw": "raw data"}
        chunks_with_meta = [Chunk(text="summary", metadata=rich_meta)]
        seen_meta: list[dict] = []

        def meta_recording_embedder(chunks: list[Chunk], a: str, t: str) -> int:
            seen_meta.extend(c.metadata for c in chunks)
            return len(chunks)

        use_case, _ = self._make_use_case(
            chunker=lambda a, t, s: chunks_with_meta,
            embedder=meta_recording_embedder,
        )
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert seen_meta[0] == rich_meta

    # --- Idempotency guard ------------------------------------------------

    def test_already_embedded_raises_asset_already_embedded_error(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 5)
        use_case, _ = self._make_use_case(vector_store=store)
        with pytest.raises(AssetAlreadyEmbeddedError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_already_embedded_error_message_contains_asset_id(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 5)
        use_case, _ = self._make_use_case(vector_store=store)
        with pytest.raises(AssetAlreadyEmbeddedError, match=ASSET_ID):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_already_embedded_does_not_call_chunker(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 5)
        chunker_called = [False]

        def sentinel_chunker(a: str, t: str, s: str) -> list[Chunk]:
            chunker_called[0] = True
            return []

        use_case, _ = self._make_use_case(chunker=sentinel_chunker, vector_store=store)
        with pytest.raises(AssetAlreadyEmbeddedError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        assert chunker_called[0] is False

    def test_different_tenant_same_asset_not_blocked(self):
        store = InMemoryVectorStore()
        store.save_vectors(ASSET_ID, TENANT_ID, 5)
        use_case, _ = self._make_use_case(vector_store=store)
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=OTHER_TENANT,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.tenant_id == OTHER_TENANT

    # --- Failure paths ----------------------------------------------------

    def test_chunker_failure_propagates(self):
        use_case, _ = self._make_use_case(chunker=_failing_chunker)
        with pytest.raises(RuntimeError, match="chunker simulated failure"):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_chunker_failure_does_not_save_vectors(self):
        use_case, store = self._make_use_case(chunker=_failing_chunker)
        with pytest.raises(RuntimeError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        assert store.has_vectors(ASSET_ID, TENANT_ID) is False

    def test_embedder_failure_propagates(self):
        use_case, _ = self._make_use_case(embedder=_failing_embedder)
        with pytest.raises(RuntimeError, match="embedder simulated failure"):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_embedder_failure_does_not_save_vectors(self):
        use_case, store = self._make_use_case(embedder=_failing_embedder)
        with pytest.raises(RuntimeError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        assert store.has_vectors(ASSET_ID, TENANT_ID) is False

    # --- Edge cases -------------------------------------------------------

    def test_empty_chunk_list_returns_zero_vector_count(self):
        use_case, store = self._make_use_case(
            chunker=lambda a, t, s: [],
            embedder=lambda chunks, a, t: 0,
        )
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.vector_count == 0
        assert store.count(ASSET_ID, TENANT_ID) == 0

    def test_second_call_after_failure_can_succeed(self):
        """After a failure the asset is not saved — a retry can succeed."""
        attempts = [0]

        def fails_once(a: str, t: str, s: str) -> list[Chunk]:
            attempts[0] += 1
            if attempts[0] == 1:
                raise RuntimeError("transient")
            return [Chunk(text="ok", metadata={})]

        use_case, store = self._make_use_case(chunker=fails_once)

        with pytest.raises(RuntimeError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        assert store.has_vectors(ASSET_ID, TENANT_ID) is False

        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.vector_count == 1
        assert store.has_vectors(ASSET_ID, TENANT_ID) is True

    def test_two_different_assets_embedded_independently(self):
        use_case, store = self._make_use_case()
        use_case.execute(
            asset_id="asset-X", tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id="t1",
        )
        use_case.execute(
            asset_id="asset-Y", tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id="t2",
        )
        assert store.has_vectors("asset-X", TENANT_ID) is True
        assert store.has_vectors("asset-Y", TENANT_ID) is True
