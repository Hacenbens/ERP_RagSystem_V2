from __future__ import annotations

from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class InMemoryVectorStore(VectorStorePort):
    """Thread-safe in-memory vector store for tests and local dev.

    Data is lost when the process exits — never use in production.
    """

    def __init__(self) -> None:
        # key: (asset_id, tenant_id) → vector_count
        self._store: dict[tuple[str, str], int] = {}

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

    def clear(self) -> None:
        """Reset the store between test cases."""
        self._store.clear()


__all__ = ["InMemoryVectorStore"]
