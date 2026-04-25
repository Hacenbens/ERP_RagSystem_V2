"""
Port: AssetStoragePort

Abstract interface for binary asset storage used by the ingestion pipeline.
Infrastructure implementations live in src/infrastructure/storage/.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class AssetStoragePort(ABC):
    """Store and retrieve raw uploaded document bytes."""

    @abstractmethod
    def save_bytes(
        self,
        tenant_id: str,
        asset_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        """Persist the asset bytes and return its storage key."""

    @abstractmethod
    def read_bytes(self, tenant_id: str, storage_key: str) -> bytes:
        """Load previously stored bytes for the given tenant and storage key."""

    @abstractmethod
    def delete_bytes(self, tenant_id: str, storage_key: str) -> None:
        """Delete the stored asset bytes for the given tenant and storage key."""


__all__ = ["AssetStoragePort"]
