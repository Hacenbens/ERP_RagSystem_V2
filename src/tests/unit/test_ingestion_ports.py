"""
Unit tests for ingestion-related domain ports.
"""
from __future__ import annotations

import pytest

from src.domain.models.embedding_consistency import AssetRef
from src.domain.chunk import Chunk
from src.domain.ports import (
    AssetStoragePort,
    ChunkStorePort,
    JobDispatcherPort,
)


class _AssetStorageStub(AssetStoragePort):
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], bytes] = {}

    def save_bytes(
        self,
        tenant_id: str,
        asset_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        storage_key = f"{tenant_id}/{asset_id}/{filename}"
        self.saved[(tenant_id, storage_key)] = content
        return storage_key

    def read_bytes(self, tenant_id: str, storage_key: str) -> bytes:
        return self.saved[(tenant_id, storage_key)]

    def delete_bytes(self, tenant_id: str, storage_key: str) -> None:
        self.saved.pop((tenant_id, storage_key), None)


class _ChunkStoreStub(ChunkStorePort):
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], list[Chunk]] = {}

    def save_chunks(
        self,
        asset_id: str,
        tenant_id: str,
        chunks: list[Chunk],
    ) -> int:
        self.store[(asset_id, tenant_id)] = list(chunks)
        return len(chunks)

    def find_by_asset(self, asset_id: str, tenant_id: str) -> list[Chunk]:
        return list(self.store.get((asset_id, tenant_id), []))

    def delete_by_asset(self, asset_id: str, tenant_id: str) -> int:
        chunks = self.store.pop((asset_id, tenant_id), [])
        return len(chunks)

    def list_assets(self) -> list[AssetRef]:
        return [AssetRef(asset_id=a, tenant_id=t) for (a, t) in self.store]


class _JobDispatcherStub(JobDispatcherPort):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def dispatch_ingest(
        self,
        asset_id: str,
        tenant_id: str,
        chunk_strategy: str,
        storage_key: str = "t/a/doc.txt",
    ) -> str:
        self.calls.append(("ingest", asset_id, tenant_id, chunk_strategy))
        return "task-ingest-1"

    def dispatch_embed(
        self,
        asset_id: str,
        tenant_id: str,
        chunk_strategy: str,
    ) -> str:
        self.calls.append(("embed", asset_id, tenant_id, chunk_strategy))
        return "task-embed-1"


class TestAssetStoragePort:
    def test_save_read_delete_bytes_round_trip(self) -> None:
        storage = _AssetStorageStub()

        key = storage.save_bytes(
            tenant_id="tenant-1",
            asset_id="asset-1",
            filename="policy.md",
            content=b"hello world",
        )

        assert key == "tenant-1/asset-1/policy.md"
        assert storage.read_bytes("tenant-1", key) == b"hello world"

        storage.delete_bytes("tenant-1", key)

        with pytest.raises(KeyError):
            storage.read_bytes("tenant-1", key)


class TestChunkStorePort:
    def test_save_find_delete_asset_chunks(self) -> None:
        store = _ChunkStoreStub()
        chunks = [
            Chunk(text="Part 1", metadata={"section": "A"}),
            Chunk(text="Part 2", metadata={"section": "B"}),
        ]

        saved = store.save_chunks("asset-1", "tenant-1", chunks)

        assert saved == 2
        assert store.find_by_asset("asset-1", "tenant-1") == chunks
        assert store.delete_by_asset("asset-1", "tenant-1") == 2
        assert store.find_by_asset("asset-1", "tenant-1") == []


class TestJobDispatcherPort:
    def test_dispatch_methods_return_task_ids_and_record_calls(self) -> None:
        dispatcher = _JobDispatcherStub()

        ingest_task_id = dispatcher.dispatch_ingest("asset-1", "tenant-1", "SOP")
        embed_task_id = dispatcher.dispatch_embed("asset-1", "tenant-1", "SOP")

        assert ingest_task_id == "task-ingest-1"
        assert embed_task_id == "task-embed-1"
        assert dispatcher.calls == [
            ("ingest", "asset-1", "tenant-1", "SOP"),
            ("embed", "asset-1", "tenant-1", "SOP"),
        ]
