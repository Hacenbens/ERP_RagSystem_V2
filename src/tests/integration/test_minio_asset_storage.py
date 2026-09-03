"""
MinioAssetStorage against a real MinIO server — Sprint 11 (G2·3).

LocalAssetStorage was the only AssetStoragePort implementation, and it writes
to a filesystem path. The API container and the worker container each have
their own, so an upload landed on one and the worker looked on the other and
found nothing — the B-4 storage-key failure reproduced at the container
boundary. A shared compose volume papers over that on a single host; an object
store is what survives more than one.

These run against a real MinIO, not a mock. The failure modes that matter here
— tenant isolation on the key, a missing object raising FileNotFoundError
rather than an S3Error, connections released — are exactly the ones a mocked
client would confirm regardless of whether the code is right.

Skipped unless MINIO_TEST_ENDPOINT is set:

    docker run -d -p 9199:9000 \\
      -e MINIO_ROOT_USER=testkey -e MINIO_ROOT_PASSWORD=testsecret123 \\
      minio/minio server /data
    MINIO_TEST_ENDPOINT=127.0.0.1:9199 pytest src/tests/integration/test_minio_asset_storage.py
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from src.infrastructure.storage.local_asset_storage import LocalAssetStorage
from src.infrastructure.storage.minio_asset_storage import MinioAssetStorage

ENDPOINT = os.environ.get("MINIO_TEST_ENDPOINT", "")

pytestmark = pytest.mark.skipif(
    not ENDPOINT,
    reason="MINIO_TEST_ENDPOINT not set — needs a running MinIO server",
)

TENANT = "tenant-ferza"
CONTENT = b"Purchase requisitions above 50000 DZD require finance director approval."


@pytest.fixture()
def storage() -> Iterator[MinioAssetStorage]:
    yield MinioAssetStorage(
        endpoint=ENDPOINT,
        access_key=os.environ.get("MINIO_TEST_ACCESS_KEY", "testkey"),
        secret_key=os.environ.get("MINIO_TEST_SECRET_KEY", "testsecret123"),
        bucket=f"test-{uuid.uuid4().hex[:12]}",
        secure=False,
    )


class TestRoundTrip:
    def test_saved_bytes_come_back_unchanged(self, storage):
        key = storage.save_bytes(TENANT, "A1", "sop.txt", CONTENT)

        assert storage.read_bytes(TENANT, key) == CONTENT

    def test_the_key_format_matches_local_storage(self, storage, tmp_path):
        """The two must be interchangeable: a job queued against one resolves
        against the other, so the key format cannot diverge."""
        local = LocalAssetStorage(base_path=str(tmp_path))

        minio_key = storage.save_bytes(TENANT, "A1", "sop.txt", CONTENT)
        local_key = local.save_bytes(TENANT, "A1", "sop.txt", CONTENT)

        assert minio_key == local_key == f"{TENANT}/A1/sop.txt"

    def test_a_second_client_reads_what_the_first_wrote(self, storage):
        """The point of the whole exercise: two processes, one store."""
        key = storage.save_bytes(TENANT, "A1", "sop.txt", CONTENT)

        other = MinioAssetStorage(
            endpoint=ENDPOINT,
            access_key=os.environ.get("MINIO_TEST_ACCESS_KEY", "testkey"),
            secret_key=os.environ.get("MINIO_TEST_SECRET_KEY", "testsecret123"),
            bucket=storage._bucket,
            secure=False,
        )

        assert other.read_bytes(TENANT, key) == CONTENT

    def test_empty_content_round_trips(self, storage):
        key = storage.save_bytes(TENANT, "A1", "empty.txt", b"")

        assert storage.read_bytes(TENANT, key) == b""

    def test_binary_content_is_not_mangled(self, storage):
        blob = bytes(range(256)) * 4
        key = storage.save_bytes(TENANT, "A1", "blob.bin", blob)

        assert storage.read_bytes(TENANT, key) == blob


class TestTenantIsolation:
    def test_another_tenant_cannot_read_the_key(self, storage):
        key = storage.save_bytes(TENANT, "A1", "sop.txt", CONTENT)

        with pytest.raises(FileNotFoundError):
            storage.read_bytes("other-tenant", key)

    def test_another_tenant_cannot_delete_the_key(self, storage):
        key = storage.save_bytes(TENANT, "A1", "sop.txt", CONTENT)

        with pytest.raises(FileNotFoundError):
            storage.delete_bytes("other-tenant", key)

        assert storage.read_bytes(TENANT, key) == CONTENT

    def test_a_bare_asset_id_is_rejected(self, storage):
        """The B-4 regression: the worker was handed an asset_id, not a key."""
        storage.save_bytes(TENANT, "A1", "sop.txt", CONTENT)

        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT, "A1")


class TestMissingObjects:
    def test_reading_an_absent_key_raises_file_not_found(self, storage):
        """Not an S3Error: IngestAssetUseCase catches FileNotFoundError, and
        both storage implementations must fail the same way."""
        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT, f"{TENANT}/nope/missing.txt")

    def test_deleting_an_absent_key_raises_file_not_found(self, storage):
        """remove_object alone is idempotent and would report success."""
        with pytest.raises(FileNotFoundError):
            storage.delete_bytes(TENANT, f"{TENANT}/nope/missing.txt")

    def test_delete_then_read_raises(self, storage):
        key = storage.save_bytes(TENANT, "A1", "sop.txt", CONTENT)
        storage.delete_bytes(TENANT, key)

        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT, key)


class TestBucketLifecycle:
    def test_the_bucket_is_created_on_first_use(self, storage):
        assert storage._client.bucket_exists(storage._bucket)

    def test_a_second_instance_on_the_same_bucket_does_not_fail(self, storage):
        """Two workers starting together race on make_bucket."""
        again = MinioAssetStorage(
            endpoint=ENDPOINT,
            access_key=os.environ.get("MINIO_TEST_ACCESS_KEY", "testkey"),
            secret_key=os.environ.get("MINIO_TEST_SECRET_KEY", "testsecret123"),
            bucket=storage._bucket,
            secure=False,
        )

        assert again._client.bucket_exists(storage._bucket)


class TestPortConformance:
    def test_it_is_an_asset_storage_port(self, storage):
        from src.domain.ports.asset_storage_port import AssetStoragePort

        assert isinstance(storage, AssetStoragePort)

    def test_the_ingest_use_case_can_drive_it(self, storage):
        """End to end through the use case that consumes the port."""
        from src.domain.chunk import Chunk
        from src.infrastructure.persistence.chunk_store import InMemoryChunkStore
        from src.infrastructure.workers.idempotency_store import InMemoryIdempotencyStore
        from src.use_cases.tasks.ingest_asset_use_case import IngestAssetUseCase

        key = storage.save_bytes(TENANT, "A1", "sop.txt", CONTENT)
        chunk_store = InMemoryChunkStore()

        result = IngestAssetUseCase(
            idempotency_store=InMemoryIdempotencyStore(),
            asset_storage=storage,
            chunk_store=chunk_store,
            chunker=lambda content, strategy: [Chunk(text=content.decode())],
        ).execute(
            asset_id="A1",
            tenant_id=TENANT,
            chunk_strategy="SOP",
            task_id="t-1",
            storage_key=key,
        )

        assert result.chunk_count == 1
        assert chunk_store.find_by_asset("A1", TENANT)[0].text == CONTENT.decode()
