"""
MongoVectorStore — Sprint 6 production vector metadata store.

Tracks which assets have been embedded and how many vectors they produced,
using a MongoDB collection (``embedded_assets``).  Actual float vectors will
be stored in Milvus starting Sprint 7; for Sprint 6 this store provides the
idempotency guard only.

Document schema:
    {
        "asset_id":     str,
        "tenant_id":    str,
        "vector_count": int,
        "embedded_at":  ISO-8601 str,
    }

Compound unique index on (asset_id, tenant_id) must be created at deploy time:
    db.embedded_assets.create_index(
        [("asset_id", 1), ("tenant_id", 1)], unique=True
    )
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class MongoVectorStore(VectorStorePort):
    """MongoDB-backed vector metadata store for production use.

    Args:
        collection: A pymongo Collection pointing to ``embedded_assets``.
    """

    def __init__(self, collection: Any) -> None:
        self._col = collection

    def has_vectors(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if a document exists for this (asset_id, tenant_id)."""
        return (
            self._col.count_documents(
                {"asset_id": asset_id, "tenant_id": tenant_id}, limit=1
            )
            > 0
        )

    def save_vectors(self, asset_id: str, tenant_id: str, vector_count: int) -> None:
        """Upsert the vector metadata record for the given asset."""
        self._col.update_one(
            {"asset_id": asset_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "vector_count": vector_count,
                    "embedded_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
        logger.debug(
            "vector_store.mongo.saved",
            asset_id=asset_id,
            tenant_id=tenant_id,
            vector_count=vector_count,
        )

    def count(self, asset_id: str, tenant_id: str) -> int:
        """Return stored vector count, or 0 if no record exists."""
        doc = self._col.find_one(
            {"asset_id": asset_id, "tenant_id": tenant_id},
            {"vector_count": 1},
        )
        return int(doc["vector_count"]) if doc else 0


__all__ = ["MongoVectorStore"]
