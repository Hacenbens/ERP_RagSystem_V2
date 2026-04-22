from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EmbedResult:
    """Outcome of a successful vector embedding task."""

    asset_id: str
    tenant_id: str
    vector_count: int
    chunk_strategy: str
    duration_ms: float
    task_id: str


__all__ = ["EmbedResult"]
