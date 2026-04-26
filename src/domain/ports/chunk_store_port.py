"""
Port: ChunkStorePort

Abstract interface for persisting document chunks and their metadata.
Infrastructure implementations live in src/infrastructure/persistence/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.chunk import Chunk


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


__all__ = ["ChunkStorePort"]
