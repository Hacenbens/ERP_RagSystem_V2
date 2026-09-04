"""
MinioAssetStorage — AssetStoragePort backed by MinIO (S3-compatible).

LocalAssetStorage was the only implementation, and it writes to a local
filesystem path. The API container and the worker container each have their
own, so an upload landed on one and the worker looked on the other and found
nothing — the B-4 storage-key failure reproduced at the container boundary.
A shared compose volume papers over that on one host; an object store is what
survives more than one.

Keys are ``{tenant_id}/{asset_id}/{filename}``, matching LocalAssetStorage, so
the two are interchangeable and a job queued against one resolves against the
other. Tenant isolation is enforced the same way: the key must carry the
caller's tenant as its first segment, so a key belonging to tenant A cannot be
read by presenting it as tenant B.
"""
from __future__ import annotations

import io
import os

from minio import Minio
from minio.error import S3Error

from src.domain.ports.asset_storage_port import AssetStoragePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_DEFAULT_BUCKET = "erp-rag-assets"


class MinioAssetStorage(AssetStoragePort):
    """Store asset bytes in a MinIO bucket.

    Args:
        endpoint: ``host:port`` (no scheme) — MinIO's own convention.
        access_key / secret_key: credentials.
        bucket: bucket name, created on first use if absent.
        secure: TLS. Defaults to False because compose runs MinIO on plain
            HTTP inside the bridge network; set it for anything reachable
            from outside.
        client: inject a pre-built client (tests, or a custom config).
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str = _DEFAULT_BUCKET,
        secure: bool = False,
        client: Minio | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = client or Minio(
            endpoint or os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
            access_key=access_key or os.environ.get("MINIO_ACCESS_KEY", ""),
            secret_key=secret_key or os.environ.get("MINIO_SECRET_KEY", ""),
            secure=secure,
        )
        self._ensure_bucket()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_bucket(self) -> None:
        """Create the bucket on first use.

        Racy by nature — two workers can start together — so an already-owned
        bucket is treated as success rather than an error.
        """
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info("minio_storage.bucket_created", bucket=self._bucket)
        except S3Error as exc:
            if exc.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise

    @staticmethod
    def _object_name(tenant_id: str, storage_key: str) -> str:
        """Return the object name for *storage_key*, enforcing tenant isolation.

        The key format is ``{tenant_id}/{asset_id}/{filename}``. Verifying the
        prefix here means a key issued for one tenant cannot be replayed by
        another, which is the same guarantee LocalAssetStorage._resolve makes.
        """
        parts = storage_key.split("/", 1)
        if len(parts) < 2 or parts[0] != tenant_id:
            raise FileNotFoundError(
                f"Storage key {storage_key!r} does not belong to tenant {tenant_id!r}"
            )
        return storage_key

    # ------------------------------------------------------------------
    # AssetStoragePort
    # ------------------------------------------------------------------

    def save_bytes(
        self,
        tenant_id: str,
        asset_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        """Upload the asset and return its storage key."""
        storage_key = f"{tenant_id}/{asset_id}/{filename}"
        self._client.put_object(
            self._bucket,
            storage_key,
            io.BytesIO(content),
            length=len(content),
        )
        logger.info(
            "minio_storage.saved",
            bucket=self._bucket,
            storage_key=storage_key,
            size_bytes=len(content),
        )
        return storage_key

    def read_bytes(self, tenant_id: str, storage_key: str) -> bytes:
        """Return the stored bytes.

        Raises FileNotFoundError when the object is absent or belongs to a
        different tenant — the same exception LocalAssetStorage raises, so
        IngestAssetUseCase handles both identically.
        """
        name = self._object_name(tenant_id, storage_key)
        response = None
        try:
            response = self._client.get_object(self._bucket, name)
            return response.read()
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                raise FileNotFoundError(
                    f"Asset not found: {storage_key!r} for tenant {tenant_id!r}"
                ) from exc
            raise
        finally:
            # MinIO holds the connection open until both are called.
            if response is not None:
                response.close()
                response.release_conn()

    def delete_bytes(self, tenant_id: str, storage_key: str) -> None:
        """Delete the stored asset.

        Raises FileNotFoundError when absent, matching LocalAssetStorage:
        remove_object alone is idempotent and would report success for a key
        that was never there.
        """
        name = self._object_name(tenant_id, storage_key)
        try:
            self._client.stat_object(self._bucket, name)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                raise FileNotFoundError(
                    f"Asset not found: {storage_key!r} for tenant {tenant_id!r}"
                ) from exc
            raise
        self._client.remove_object(self._bucket, name)
        logger.info("minio_storage.deleted", bucket=self._bucket, storage_key=name)


__all__ = ["MinioAssetStorage"]
