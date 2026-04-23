from __future__ import annotations

import math
from dataclasses import dataclass

from src.domain.models.scored_chunk import ScoredChunk
from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


@dataclass
class _VectorRecord:
    chunk_id: str
    content: str
    embedding: list[float]
    asset_id: str
    tenant_id: str
    erp_module: str | None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorStore(VectorStorePort):
    """Thread-safe in-memory vector store for tests and local dev.

    Data is lost when the process exits — never use in production.
    """

    def __init__(self) -> None:
        # key: (asset_id, tenant_id) → vector_count
        self._store: dict[tuple[str, str], int] = {}
        self._vectors: list[_VectorRecord] = []

    # ------------------------------------------------------------------
    # Sprint 6 — idempotency tracking
    # ------------------------------------------------------------------

    def has_vectors(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if vectors were previously saved for this asset."""
        return (asset_id, tenant_id) in self._store

    def save_vectors(self, asset_id: str, tenant_id: str, vector_count: int) -> None:
        """Record the vector count for the given asset."""
        self._store[(asset_id, tenant_id)] = vector_count
        logger.debug(
            "vector_store.in_memory.saved",
            asset_id=asset_id,
            tenant_id=tenant_id,
            vector_count=vector_count,
        )

    def count(self, asset_id: str, tenant_id: str) -> int:
        """Return stored vector count, or 0 if asset has never been embedded."""
        return self._store.get((asset_id, tenant_id), 0)

    # ------------------------------------------------------------------
    # Sprint 7 — vector search
    # ------------------------------------------------------------------

    def upsert(
        self,
        asset_id: str,
        tenant_id: str,
        embedding: list[float],
        chunk_id: str,
        content: str,
        erp_module: str | None = None,
    ) -> None:
        """Store or replace the embedding for a single chunk (idempotent)."""
        self._vectors = [r for r in self._vectors if r.chunk_id != chunk_id]
        self._vectors.append(
            _VectorRecord(
                chunk_id=chunk_id,
                content=content,
                embedding=embedding,
                asset_id=asset_id,
                tenant_id=tenant_id,
                erp_module=erp_module,
            )
        )
        logger.debug(
            "vector_store.in_memory.upserted",
            chunk_id=chunk_id,
            asset_id=asset_id,
            tenant_id=tenant_id,
        )

    def search_similar(
        self,
        query_embedding: list[float],
        k: int,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> list[ScoredChunk]:
        """Return the top-k chunks most similar to query_embedding.

        Scoped to tenant_id; further filtered by erp_module when provided.
        """
        candidates = [
            r for r in self._vectors
            if r.tenant_id == tenant_id
            and (erp_module is None or r.erp_module == erp_module)
        ]
        scored = sorted(
            ((_cosine(query_embedding, r.embedding), r) for r in candidates),
            key=lambda t: t[0],
            reverse=True,
        )
        return [
            ScoredChunk(
                chunk_id=r.chunk_id,
                content=r.content,
                score=score,
                source=r.asset_id,
                erp_module=r.erp_module,
            )
            for score, r in scored[:k]
        ]

    def clear(self) -> None:
        """Reset the store between test cases."""
        self._store.clear()
        self._vectors.clear()


__all__ = ["InMemoryVectorStore"]
