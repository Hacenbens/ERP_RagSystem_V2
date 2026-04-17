"""
Dead-letter repository implementations.

InMemoryDeadLetterRepository  — tests and local dev (no MongoDB required)
MongoDeadLetterRepository     — production (writes to failed_tasks collection)
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.domain.ingest import FailedTaskEntry
from src.domain.ports.dead_letter_repository import DeadLetterRepositoryPort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class InMemoryDeadLetterRepository(DeadLetterRepositoryPort):
    """Thread-safe in-memory store backed by a plain list.

    Intended for tests and CI only — data is lost when the process exits.
    """

    def __init__(self) -> None:
        self._entries: list[FailedTaskEntry] = []

    def save(self, entry: FailedTaskEntry) -> None:
        """Append the entry to the in-memory list."""
        self._entries.append(entry)
        logger.error(
            "dead_letter.saved",
            task_id=entry.task_id,
            asset_id=entry.asset_id,
            tenant_id=entry.tenant_id,
            exception_type=entry.exception_type,
        )

    def count(self) -> int:
        """Return number of dead-letter entries."""
        return len(self._entries)

    def get_all(self) -> list[FailedTaskEntry]:
        """Return a copy of all entries (test helper)."""
        return list(self._entries)

    def find_by_asset(self, asset_id: str, tenant_id: str) -> list[FailedTaskEntry]:
        """Return entries matching the given asset/tenant pair (test helper)."""
        return [
            e for e in self._entries
            if e.asset_id == asset_id and e.tenant_id == tenant_id
        ]

    def clear(self) -> None:
        """Reset the store between test cases."""
        self._entries.clear()


class MongoDeadLetterRepository(DeadLetterRepositoryPort):
    """MongoDB-backed dead-letter store for production use.

    Args:
        collection: A pymongo (or mongomock) Collection instance pointing
                    to the ``failed_tasks`` collection.
    """

    def __init__(self, collection: Any) -> None:
        self._col = collection

    def save(self, entry: FailedTaskEntry) -> None:
        """Insert the dead-letter entry into MongoDB.

        Never raises — logs on failure to avoid masking the original error.
        """
        try:
            self._col.insert_one(asdict(entry))
            logger.error(
                "dead_letter.mongo_saved",
                task_id=entry.task_id,
                asset_id=entry.asset_id,
            )
        except Exception as exc:
            logger.error(
                "dead_letter.mongo_save_failed",
                task_id=entry.task_id,
                asset_id=entry.asset_id,
                error=str(exc),
            )

    def count(self) -> int:
        """Return the number of documents in the failed_tasks collection."""
        return int(self._col.count_documents({}))


__all__ = ["InMemoryDeadLetterRepository", "MongoDeadLetterRepository"]
