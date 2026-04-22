"""
Port: VectorStorePort

Abstract interface for tracking which assets have been embedded and
how many vectors they produced.  Infrastructure implementations live
in src/infrastructure/vector_store/.

Sprint 6: idempotency tracking (has_vectors / save_vectors).
Sprint 7: extend with upsert_embeddings(asset_id, tenant_id, vectors) for
          real float-vector storage in Milvus.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class VectorStorePort(ABC):
    """Track embedding status and vector counts per asset."""

    @abstractmethod
    def has_vectors(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if this asset already has stored vectors."""

    @abstractmethod
    def save_vectors(self, asset_id: str, tenant_id: str, vector_count: int) -> None:
        """Record that *vector_count* vectors were stored for this asset."""

    @abstractmethod
    def count(self, asset_id: str, tenant_id: str) -> int:
        """Return the number of vectors stored for this asset (0 if none)."""


__all__ = ["VectorStorePort"]
