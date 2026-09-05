"""
Port: ChunkStorePort

Abstract interface for persisting document chunks and their metadata.
Infrastructure implementations live in src/infrastructure/persistence/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.chunk import Chunk
from src.domain.models.embedding_consistency import AssetRef


class ChunkStorePort(ABC):
    """Persist and retrieve chunks for one asset within one tenant."""

    @abstractmethod
    def save_chunks(
        self,
        asset_id: str,
        tenant_id: str,
        chunks: list[Chunk],
    ) -> int:
        """Persist the asset chunks and return the number of chunks written."""

    @abstractmethod
    def find_by_asset(self, asset_id: str, tenant_id: str) -> list[Chunk]:
        """Return all chunks stored for the given asset and tenant."""

    @abstractmethod
    def delete_by_asset(self, asset_id: str, tenant_id: str) -> int:
        """Delete all chunks for the given asset and return the number deleted."""

    @abstractmethod
    def list_assets(self) -> list[AssetRef]:
        """Return every (asset_id, tenant_id) this store holds chunks for.

        Reconciling the chunk store against the vector store needs to start
        from what was ingested, and every other method here requires already
        knowing the asset. Across all tenants deliberately: an operator fixing
        a stalled embed does not know in advance which tenants are affected.
        """


__all__ = ["ChunkStorePort"]
