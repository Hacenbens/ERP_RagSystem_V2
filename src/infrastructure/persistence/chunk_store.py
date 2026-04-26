from __future__ import annotations

from typing import Any

from src.domain.chunk import Chunk
from src.domain.ports.chunk_store_port import ChunkStorePort


class InMemoryChunkStore(ChunkStorePort):
    """In-process chunk store backed by a plain dict — for tests and local runs."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], list[Chunk]] = {}

    def save_chunks(self, asset_id: str, tenant_id: str, chunks: list[Chunk]) -> int:
        """Upsert (replace) all chunks for (asset_id, tenant_id). Returns count written."""
        self._store[(asset_id, tenant_id)] = list(chunks)
        return len(chunks)

    def find_by_asset(self, asset_id: str, tenant_id: str) -> list[Chunk]:
        """Return stored chunks; empty list if none."""
        return list(self._store.get((asset_id, tenant_id), []))

    def delete_by_asset(self, asset_id: str, tenant_id: str) -> int:
        """Remove all chunks for (asset_id, tenant_id) and return the count deleted."""
        existing = self._store.pop((asset_id, tenant_id), [])
        return len(existing)


class MongoChunkStore(ChunkStorePort):
    """MongoDB-backed chunk store.

    Requires a pymongo collection.  Pass ``collection=None`` to get a guard
    that raises ``NotImplementedError`` on every call (useful as a test sentinel).
    """

    def __init__(self, collection: Any) -> None:
        self._col = collection

    def save_chunks(self, asset_id: str, tenant_id: str, chunks: list[Chunk]) -> int:
        """Upsert all chunks: delete existing then bulk-insert new ones."""
        self._col.delete_many({"asset_id": asset_id, "tenant_id": tenant_id})
        if not chunks:
            return 0
        docs = [
            {
                "asset_id": asset_id,
                "tenant_id": tenant_id,
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "metadata": chunk.metadata,
            }
            for chunk in chunks
        ]
        self._col.insert_many(docs)
        return len(docs)

    def find_by_asset(self, asset_id: str, tenant_id: str) -> list[Chunk]:
        """Return all chunks stored for (asset_id, tenant_id)."""
        docs = self._col.find({"asset_id": asset_id, "tenant_id": tenant_id})
        return [
            Chunk(text=doc["text"], metadata=doc.get("metadata", {}), chunk_id=doc["chunk_id"])
            for doc in docs
        ]

    def delete_by_asset(self, asset_id: str, tenant_id: str) -> int:
        """Remove all chunks for (asset_id, tenant_id) and return count deleted."""
        result = self._col.delete_many({"asset_id": asset_id, "tenant_id": tenant_id})
        return result.deleted_count


__all__ = ["InMemoryChunkStore", "MongoChunkStore"]
