"""
Port: DeadLetterRepositoryPort

Abstract interface for the dead-letter store.
Infrastructure implementations live in src/infrastructure/workers/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.ingest import FailedTaskEntry


class DeadLetterRepositoryPort(ABC):
    """Write-only port for the failed_tasks dead-letter collection."""

    @abstractmethod
    def save(self, entry: FailedTaskEntry) -> None:
        """Persist a dead-letter entry.  Must never raise."""

    @abstractmethod
    def count(self) -> int:
        """Return the number of entries (used in tests)."""


__all__ = ["DeadLetterRepositoryPort"]
