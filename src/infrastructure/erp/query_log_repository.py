"""
Query Log Repository — Sprint 4
Records every ExecutionResult to MongoDB query_log collection.

In test mode (no real MongoDB), uses an in-memory list.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional
from uuid import uuid4

from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


@dataclass
class QueryLogEntry:
    query_id: str
    nl_query: str
    sql: str
    tenant_id: str
    row_count: int
    latency_ms: float
    error: Optional[str] = None


class InMemoryQueryLogRepository:
    """In-memory query log for tests and local dev."""

    def __init__(self) -> None:
        self._log: list[QueryLogEntry] = []

    def save(self, entry: QueryLogEntry) -> None:
        self._log.append(entry)
        logger.info("query_log.saved", query_id=entry.query_id, row_count=entry.row_count)

    def get_all(self) -> list[QueryLogEntry]:
        return list(self._log)

    def get_by_id(self, query_id: str) -> Optional[QueryLogEntry]:
        return next((e for e in self._log if e.query_id == query_id), None)

    def count(self) -> int:
        return len(self._log)


class MongoQueryLogRepository:
    """MongoDB-backed query log. Used in production."""

    def __init__(self, collection) -> None:
        self._col = collection

    def save(self, entry: QueryLogEntry) -> None:
        try:
            self._col.insert_one(asdict(entry))
            logger.info("query_log.mongo_saved", query_id=entry.query_id)
        except Exception as exc:
            logger.error("query_log.mongo_save_failed", query_id=entry.query_id, error=str(exc))


__all__ = [
    "QueryLogEntry",
    "InMemoryQueryLogRepository",
    "MongoQueryLogRepository",
]
