"""
Domain models for the document ingestion pipeline.

These are pure data classes — no infrastructure dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class IngestResult:
    """Outcome of a successful document ingestion."""

    asset_id: str
    tenant_id: str
    chunk_count: int
    chunk_strategy: str
    duration_ms: float
    task_id: str


@dataclass
class FailedTaskEntry:
    """Immutable dead-letter record written when a task exhausts all retries.

    Written to the ``failed_tasks`` collection.  Never updated or deleted.
    """

    asset_id: str
    tenant_id: str
    task_name: str
    exception_type: str
    exception_message: str
    retry_count: int
    args: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    chunk_strategy: str = ""
    failed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


__all__ = ["IngestResult", "FailedTaskEntry"]
