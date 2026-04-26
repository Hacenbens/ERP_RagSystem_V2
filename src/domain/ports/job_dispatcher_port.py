"""
Port: JobDispatcherPort

Abstract interface for dispatching async ingestion jobs.
Infrastructure implementations live in src/infrastructure/workers/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class JobDispatcherPort(ABC):
    """Dispatch Celery-backed ingestion and embedding jobs."""

    @abstractmethod
    def dispatch_ingest(
        self,
        asset_id: str,
        tenant_id: str,
        chunk_strategy: str,
    ) -> str:
        """Dispatch an ingest job and return the queued task identifier."""

    @abstractmethod
    def dispatch_embed(
        self,
        asset_id: str,
        tenant_id: str,
        chunk_strategy: str,
    ) -> str:
        """Dispatch an embed job and return the queued task identifier."""


__all__ = ["JobDispatcherPort"]
