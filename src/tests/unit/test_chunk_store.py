"""
Unit tests — InMemoryChunkStore + MongoChunkStore (Sprint 7 Task 16)
All tests are pure in-memory — no real MongoDB.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


sys.path.insert(0, str(Path(__file__).parents[4]))

from src.domain.chunk import Chunk
from src.infrastructure.persistence.chunk_store import InMemoryChunkStore, MongoChunkStore


ASSET_A = "asset-aaa"
ASSET_B = "asset-bbb"
TENANT_1 = "tenant-one"
TENANT_2 = "tenant-two"


def _chunks(n: int, tenant: str = TENANT_1) -> list[Chunk]:
    return [Chunk(text=f"chunk {i} for {tenant}", metadata={"idx": i}) for i in range(n)]


# ===========================================================================
# InMemoryChunkStore
# ===========================================================================

class TestInMemoryChunkStoreSave:
    def test_save_returns_chunk_count(self):
        store = InMemoryChunkStore()
        assert store.save_chunks(ASSET_A, TENANT_1, _chunks(3)) == 3

    def test_save_empty_list_returns_zero(self):
        store = InMemoryChunkStore()
        assert store.save_chunks(ASSET_A, TENANT_1, []) == 0

    def test_save_replaces_previous_chunks(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(5))
        store.save_chunks(ASSET_A, TENANT_1, _chunks(2))
        assert len(store.find_by_asset(ASSET_A, TENANT_1)) == 2

    def test_save_does_not_append(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(3))
        store.save_chunks(ASSET_A, TENANT_1, _chunks(3))
        assert len(store.find_by_asset(ASSET_A, TENANT_1)) == 3


class TestInMemoryChunkStoreFind:
    def test_find_returns_saved_chunks(self):
        store = InMemoryChunkStore()
        original = _chunks(3)
        store.save_chunks(ASSET_A, TENANT_1, original)
        found = store.find_by_asset(ASSET_A, TENANT_1)
        assert [c.text for c in found] == [c.text for c in original]

    def test_find_empty_returns_empty_list(self):
        store = InMemoryChunkStore()
        assert store.find_by_asset(ASSET_A, TENANT_1) == []

    def test_find_returns_copy_not_reference(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(2))
        store.find_by_asset(ASSET_A, TENANT_1).clear()
        assert len(store.find_by_asset(ASSET_A, TENANT_1)) == 2

    def test_tenant_isolation(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(3, TENANT_1))
        store.save_chunks(ASSET_A, TENANT_2, _chunks(1, TENANT_2))
        assert len(store.find_by_asset(ASSET_A, TENANT_1)) == 3
        assert len(store.find_by_asset(ASSET_A, TENANT_2)) == 1

    def test_different_assets_dont_mix(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(2))
        store.save_chunks(ASSET_B, TENANT_1, _chunks(4))
        assert len(store.find_by_asset(ASSET_A, TENANT_1)) == 2
        assert len(store.find_by_asset(ASSET_B, TENANT_1)) == 4


class TestInMemoryChunkStoreDelete:
    def test_delete_returns_count(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(3))
        assert store.delete_by_asset(ASSET_A, TENANT_1) == 3

    def test_delete_removes_chunks(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(3))
        store.delete_by_asset(ASSET_A, TENANT_1)
        assert store.find_by_asset(ASSET_A, TENANT_1) == []

    def test_delete_missing_returns_zero(self):
        store = InMemoryChunkStore()
        assert store.delete_by_asset("nonexistent", TENANT_1) == 0

    def test_delete_does_not_affect_other_tenant(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(2))
        store.save_chunks(ASSET_A, TENANT_2, _chunks(3))
        store.delete_by_asset(ASSET_A, TENANT_1)
        assert len(store.find_by_asset(ASSET_A, TENANT_2)) == 3


class TestInMemoryChunkStoreRoundTrip:
    def test_save_find_delete_find(self):
        store = InMemoryChunkStore()
        store.save_chunks(ASSET_A, TENANT_1, _chunks(3))
        assert len(store.find_by_asset(ASSET_A, TENANT_1)) == 3
        store.delete_by_asset(ASSET_A, TENANT_1)
        assert store.find_by_asset(ASSET_A, TENANT_1) == []


# ===========================================================================
# MongoChunkStore — fake collection stub
# ===========================================================================

class TestMongoChunkStoreSave:
    def test_save_calls_delete_many_then_insert_many(self):
        col = MagicMock()
        store = MongoChunkStore(collection=col)
        chunks = _chunks(2)
        count = store.save_chunks(ASSET_A, TENANT_1, chunks)

        col.delete_many.assert_called_once_with({"asset_id": ASSET_A, "tenant_id": TENANT_1})
        col.insert_many.assert_called_once()
        inserted_docs = col.insert_many.call_args[0][0]
        assert len(inserted_docs) == 2
        assert count == 2

    def test_save_empty_skips_insert_many(self):
        col = MagicMock()
        store = MongoChunkStore(collection=col)
        count = store.save_chunks(ASSET_A, TENANT_1, [])

        col.delete_many.assert_called_once()
        col.insert_many.assert_not_called()
        assert count == 0

    def test_inserted_docs_have_required_fields(self):
        col = MagicMock()
        store = MongoChunkStore(collection=col)
        chunks = [Chunk(text="hello", metadata={"k": "v"})]
        store.save_chunks(ASSET_A, TENANT_1, chunks)

        doc = col.insert_many.call_args[0][0][0]
        assert doc["asset_id"] == ASSET_A
        assert doc["tenant_id"] == TENANT_1
        assert doc["text"] == "hello"
        assert doc["metadata"] == {"k": "v"}
        assert "chunk_id" in doc


class TestMongoChunkStoreFind:
    def test_find_maps_docs_to_chunks(self):
        col = MagicMock()
        col.find.return_value = [
            {"text": "t1", "metadata": {}, "chunk_id": "cid-1"},
            {"text": "t2", "metadata": {"x": 1}, "chunk_id": "cid-2"},
        ]
        store = MongoChunkStore(collection=col)
        result = store.find_by_asset(ASSET_A, TENANT_1)
        assert len(result) == 2
        assert result[0].text == "t1"
        assert result[1].metadata == {"x": 1}


class TestMongoChunkStoreDelete:
    def test_delete_returns_deleted_count(self):
        col = MagicMock()
        col.delete_many.return_value = MagicMock(deleted_count=4)
        store = MongoChunkStore(collection=col)
        assert store.delete_by_asset(ASSET_A, TENANT_1) == 4
