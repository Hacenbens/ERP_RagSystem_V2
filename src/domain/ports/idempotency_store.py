"""
Port: IdempotencyStorePort

Abstract interface for the processed-asset idempotency guard.
Infrastructure implementations live in src/infrastructure/workers/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class IdempotencyStorePort(ABC):
    """Check and record which assets have been successfully processed."""

    @abstractmethod
    def is_processed(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if this asset has already been successfully ingested."""

    @abstractmethod
    def mark_processed(self, asset_id: str, tenant_id: str) -> None:
        """Record that this asset was successfully ingested."""


__all__ = ["IdempotencyStorePort"]
