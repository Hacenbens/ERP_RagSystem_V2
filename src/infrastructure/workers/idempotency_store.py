"""
Idempotency store implementations.

InMemoryIdempotencyStore  — tests and local dev
MongoIdempotencyStore     — production (upserts into processed_assets collection)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.domain.ports.idempotency_store import IdempotencyStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class InMemoryIdempotencyStore(IdempotencyStorePort):
    """In-memory idempotency guard backed by a set.

    Key format: ``{tenant_id}:{asset_id}`` — prevents cross-tenant
    false positives (two tenants can have assets with the same ID).
    """

    def __init__(self) -> None:
        self._processed: set[str] = set()

    def _key(self, asset_id: str, tenant_id: str) -> str:
        return f"{tenant_id}:{asset_id}"

    def is_processed(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if this asset was already successfully ingested."""
        return self._key(asset_id, tenant_id) in self._processed

    def mark_processed(self, asset_id: str, tenant_id: str) -> None:
        """Record the asset as successfully processed."""
        self._processed.add(self._key(asset_id, tenant_id))
        logger.info(
            "idempotency.marked_processed",
            asset_id=asset_id,
            tenant_id=tenant_id,
        )

    def clear(self) -> None:
        """Reset the store between test cases."""
        self._processed.clear()


class MongoIdempotencyStore(IdempotencyStorePort):
    """MongoDB-backed idempotency store for production use.

    Args:
        collection: pymongo (or mongomock) Collection pointing to
                    ``processed_assets``.
    """

    def __init__(self, collection: Any) -> None:
        self._col = collection

    def is_processed(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if a success record exists for this pair."""
        return (
            self._col.find_one(
                {"asset_id": asset_id, "tenant_id": tenant_id}
            ) is not None
        )

    def mark_processed(self, asset_id: str, tenant_id: str) -> None:
        """Upsert a success record.  Safe to call multiple times."""
        self._col.update_one(
            {"asset_id": asset_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "asset_id": asset_id,
                    "tenant_id": tenant_id,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
        logger.info(
            "idempotency.mongo_marked_processed",
            asset_id=asset_id,
            tenant_id=tenant_id,
        )


__all__ = ["InMemoryIdempotencyStore", "MongoIdempotencyStore"]
