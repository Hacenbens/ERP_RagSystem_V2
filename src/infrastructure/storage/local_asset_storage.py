from __future__ import annotations

from pathlib import Path

from src.domain.ports.asset_storage_port import AssetStoragePort


class LocalAssetStorage(AssetStoragePort):
    """Store asset bytes on the local filesystem under ``{base_path}/{tenant_id}/{asset_id}/``."""

    def __init__(self, base_path: str) -> None:
        self._base = Path(base_path)

    # ------------------------------------------------------------------
    # AssetStoragePort implementation
    # ------------------------------------------------------------------

    def save_bytes(
        self,
        tenant_id: str,
        asset_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        """Write bytes to disk and return the storage key ``{tenant_id}/{asset_id}/{filename}``."""
        dest = self._asset_dir(tenant_id, asset_id) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return f"{tenant_id}/{asset_id}/{filename}"

    def read_bytes(self, tenant_id: str, storage_key: str) -> bytes:
        """Return bytes for a previously stored asset.

        Raises FileNotFoundError if the key does not exist or belongs to a
        different tenant (cross-tenant isolation).
        """
        path = self._resolve(tenant_id, storage_key)
        if not path.exists():
            raise FileNotFoundError(f"Asset not found: {storage_key!r} for tenant {tenant_id!r}")
        return path.read_bytes()

    def delete_bytes(self, tenant_id: str, storage_key: str) -> None:
        """Delete a stored asset.

        Raises FileNotFoundError if the key does not exist or belongs to a
        different tenant.
        """
        path = self._resolve(tenant_id, storage_key)
        if not path.exists():
            raise FileNotFoundError(f"Asset not found: {storage_key!r} for tenant {tenant_id!r}")
        path.unlink()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _asset_dir(self, tenant_id: str, asset_id: str) -> Path:
        return self._base / tenant_id / asset_id

    def _resolve(self, tenant_id: str, storage_key: str) -> Path:
        """Resolve storage_key to an absolute path, enforcing tenant isolation.

        The key format is ``{tenant_id}/{asset_id}/{filename}``.
        This method verifies the key's tenant prefix matches ``tenant_id``
        so a key from tenant A cannot be used to read tenant B data.
        """
        parts = storage_key.split("/", 1)
        if len(parts) < 2 or parts[0] != tenant_id:
            raise FileNotFoundError(
                f"Storage key {storage_key!r} does not belong to tenant {tenant_id!r}"
            )
        return self._base / storage_key


__all__ = ["LocalAssetStorage"]
