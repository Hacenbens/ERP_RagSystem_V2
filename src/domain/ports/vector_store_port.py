"""
Port: VectorStorePort

Abstract interface for the vector store used by the RAG pipeline.
Infrastructure implementations live in src/infrastructure/vector_store/.

Sprint 6: idempotency tracking (has_vectors / save_vectors / count).
Sprint 7: vector search (upsert / search_similar).
          Milvus wiring deferred to Sprint 8 — InMemoryVectorStore
          provides cosine-similarity search for tests and local dev.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.models.scored_chunk import ScoredChunk


class VectorStorePort(ABC):
    """Store and retrieve chunk embeddings; track embedding status per asset."""

    # ------------------------------------------------------------------
    # Sprint 6 — idempotency tracking
    # ------------------------------------------------------------------

    @abstractmethod
    def has_vectors(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if this asset already has stored vectors."""

    @abstractmethod
    def save_vectors(self, asset_id: str, tenant_id: str, vector_count: int) -> None:
        """Record that *vector_count* vectors were stored for this asset."""

    @abstractmethod
    def count(self, asset_id: str, tenant_id: str) -> int:
        """Return the number of vectors stored for this asset (0 if none)."""

    # ------------------------------------------------------------------
    # Sprint 7 — vector search
    # ------------------------------------------------------------------

    @abstractmethod
    def upsert(
        self,
        asset_id: str,
        tenant_id: str,
        embedding: list[float],
        chunk_id: str,
        content: str,
        erp_module: str | None = None,
    ) -> None:
        """Store or replace the embedding for a single chunk.

        asset_id is recorded as the chunk source for attribution.
        Idempotent: upserting the same chunk_id overwrites the previous record.
        """

    @abstractmethod
    def search_similar(
        self,
        query_embedding: list[float],
        k: int,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> list[ScoredChunk]:
        """Return the top-k chunks most similar to query_embedding.

        Results are scoped to tenant_id.
        If erp_module is provided, only chunks from that module are returned.
        Results are ordered by descending similarity score.
        """


__all__ = ["VectorStorePort"]
