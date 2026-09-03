"""
Unit tests — Sprint 7 Task 18 (refactored from Sprint 6 Task 1)
Covers: domain models, InMemory repositories, IngestAssetUseCase (new signature)

All tests are pure in-memory — no Celery, no MongoDB, no I/O.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.domain.chunk import Chunk
from src.domain.ingest import FailedTaskEntry, IngestResult
from src.domain.ports.asset_storage_port import AssetStoragePort
from src.infrastructure.persistence.chunk_store import InMemoryChunkStore
from src.infrastructure.workers.dead_letter_repository import InMemoryDeadLetterRepository
from src.infrastructure.workers.idempotency_store import InMemoryIdempotencyStore
from src.use_cases.tasks.ingest_asset_use_case import (
    AssetAlreadyProcessedError,
    IngestAssetUseCase,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ASSET_ID = "asset-abc-123"
TENANT_ID = "tenant-ferza"
OTHER_TENANT = "tenant-acme"
TASK_ID = "task-xyz-999"
STRATEGY = "sop"
CONTENT = b"sample document bytes"


def _success_chunker(content: bytes, strategy: str) -> list[Chunk]:
    """Returns 3 chunks regardless of content."""
    return [Chunk(text=f"chunk {i}", metadata={"strategy": strategy}) for i in range(3)]


def _failing_chunker(content: bytes, strategy: str) -> list[Chunk]:
    """Always raises — simulates a broken chunker."""
    raise RuntimeError("chunker simulated failure")


class _StubStorage(AssetStoragePort):
    """Minimal AssetStoragePort stub that always returns CONTENT."""
    def save_bytes(self, tenant_id, asset_id, filename, content):
        return f"{tenant_id}/{asset_id}/{filename}"
    def read_bytes(self, tenant_id, storage_key):
        return CONTENT
    def delete_bytes(self, tenant_id, storage_key):
        pass


class _MissingStorage:
    """Stub that always raises FileNotFoundError on read."""
    def save_bytes(self, tenant_id, asset_id, filename, content):
        return ""
    def read_bytes(self, tenant_id, storage_key):
        raise FileNotFoundError(f"Not found: {storage_key}")
    def delete_bytes(self, tenant_id, storage_key):
        pass


# ---------------------------------------------------------------------------
# IngestResult domain model
# ---------------------------------------------------------------------------

class TestIngestResult:
    def test_fields_stored_correctly(self):
        result = IngestResult(
            asset_id=ASSET_ID,
            tenant_id=TENANT_ID,
            chunk_count=7,
            chunk_strategy=STRATEGY,
            duration_ms=42.5,
            task_id=TASK_ID,
        )
        assert result.asset_id == ASSET_ID
        assert result.tenant_id == TENANT_ID
        assert result.chunk_count == 7
        assert result.chunk_strategy == STRATEGY
        assert result.duration_ms == 42.5
        assert result.task_id == TASK_ID


# ---------------------------------------------------------------------------
# FailedTaskEntry domain model
# ---------------------------------------------------------------------------

class TestFailedTaskEntry:
    def test_required_fields_stored(self):
        entry = FailedTaskEntry(
            asset_id=ASSET_ID,
            tenant_id=TENANT_ID,
            task_name="workers.tasks.ingest_asset",
            exception_type="RuntimeError",
            exception_message="something went wrong",
            retry_count=3,
        )
        assert entry.asset_id == ASSET_ID
        assert entry.tenant_id == TENANT_ID
        assert entry.exception_type == "RuntimeError"
        assert entry.retry_count == 3

    def test_id_auto_generated_as_uuid(self):
        entry = FailedTaskEntry(
            asset_id=ASSET_ID,
            tenant_id=TENANT_ID,
            task_name="t",
            exception_type="E",
            exception_message="msg",
            retry_count=3,
        )
        assert entry.id
        assert len(entry.id) == 36  # UUID4 format

    def test_failed_at_is_iso_utc(self):
        entry = FailedTaskEntry(
            asset_id=ASSET_ID,
            tenant_id=TENANT_ID,
            task_name="t",
            exception_type="E",
            exception_message="msg",
            retry_count=3,
        )
        assert "T" in entry.failed_at  # ISO-8601 contains 'T'
        assert "+" in entry.failed_at or "Z" in entry.failed_at or entry.failed_at.endswith("+00:00")

    def test_two_entries_have_different_ids(self):
        e1 = FailedTaskEntry(asset_id="a", tenant_id="t", task_name="n",
                             exception_type="E", exception_message="m", retry_count=3)
        e2 = FailedTaskEntry(asset_id="a", tenant_id="t", task_name="n",
                             exception_type="E", exception_message="m", retry_count=3)
        assert e1.id != e2.id


# ---------------------------------------------------------------------------
# InMemoryDeadLetterRepository
# ---------------------------------------------------------------------------

class TestInMemoryDeadLetterRepository:
    def _make_entry(self, asset_id: str = ASSET_ID, tenant_id: str = TENANT_ID) -> FailedTaskEntry:
        return FailedTaskEntry(
            asset_id=asset_id,
            tenant_id=tenant_id,
            task_name="workers.tasks.ingest_asset",
            exception_type="RuntimeError",
            exception_message="failure",
            retry_count=3,
        )

    def test_empty_repository_has_zero_count(self):
        repo = InMemoryDeadLetterRepository()
        assert repo.count() == 0

    def test_save_increments_count(self):
        repo = InMemoryDeadLetterRepository()
        repo.save(self._make_entry())
        assert repo.count() == 1

    def test_save_multiple_entries(self):
        repo = InMemoryDeadLetterRepository()
        for _ in range(3):
            repo.save(self._make_entry())
        assert repo.count() == 3

    def test_get_all_returns_saved_entries(self):
        repo = InMemoryDeadLetterRepository()
        entry = self._make_entry()
        repo.save(entry)
        all_entries = repo.get_all()
        assert len(all_entries) == 1
        assert all_entries[0].asset_id == ASSET_ID

    def test_get_all_returns_copy_not_reference(self):
        repo = InMemoryDeadLetterRepository()
        repo.save(self._make_entry())
        copy = repo.get_all()
        copy.clear()
        assert repo.count() == 1  # original unaffected

    def test_find_by_asset_returns_matching_entries(self):
        repo = InMemoryDeadLetterRepository()
        repo.save(self._make_entry(asset_id="asset-1", tenant_id=TENANT_ID))
        repo.save(self._make_entry(asset_id="asset-2", tenant_id=TENANT_ID))
        results = repo.find_by_asset("asset-1", TENANT_ID)
        assert len(results) == 1
        assert results[0].asset_id == "asset-1"

    def test_find_by_asset_different_tenant_returns_empty(self):
        repo = InMemoryDeadLetterRepository()
        repo.save(self._make_entry(asset_id=ASSET_ID, tenant_id=TENANT_ID))
        results = repo.find_by_asset(ASSET_ID, OTHER_TENANT)
        assert results == []

    def test_clear_resets_count_to_zero(self):
        repo = InMemoryDeadLetterRepository()
        repo.save(self._make_entry())
        repo.save(self._make_entry())
        repo.clear()
        assert repo.count() == 0


# ---------------------------------------------------------------------------
# InMemoryIdempotencyStore
# ---------------------------------------------------------------------------

class TestInMemoryIdempotencyStore:
    def test_new_asset_is_not_processed(self):
        store = InMemoryIdempotencyStore()
        assert store.is_processed(ASSET_ID, TENANT_ID) is False

    def test_mark_processed_changes_state(self):
        store = InMemoryIdempotencyStore()
        store.mark_processed(ASSET_ID, TENANT_ID)
        assert store.is_processed(ASSET_ID, TENANT_ID) is True

    def test_different_tenant_same_asset_not_cross_contaminated(self):
        """Tenant isolation — marking processed for one tenant must not affect another."""
        store = InMemoryIdempotencyStore()
        store.mark_processed(ASSET_ID, TENANT_ID)
        assert store.is_processed(ASSET_ID, OTHER_TENANT) is False

    def test_same_tenant_different_assets_are_independent(self):
        store = InMemoryIdempotencyStore()
        store.mark_processed("asset-A", TENANT_ID)
        assert store.is_processed("asset-B", TENANT_ID) is False

    def test_mark_processed_twice_is_idempotent(self):
        store = InMemoryIdempotencyStore()
        store.mark_processed(ASSET_ID, TENANT_ID)
        store.mark_processed(ASSET_ID, TENANT_ID)  # should not raise
        assert store.is_processed(ASSET_ID, TENANT_ID) is True

    def test_clear_resets_all_entries(self):
        store = InMemoryIdempotencyStore()
        store.mark_processed(ASSET_ID, TENANT_ID)
        store.mark_processed("other-asset", TENANT_ID)
        store.clear()
        assert store.is_processed(ASSET_ID, TENANT_ID) is False
        assert store.is_processed("other-asset", TENANT_ID) is False


# ---------------------------------------------------------------------------
# IngestAssetUseCase — Sprint 7 refactored signature
# ---------------------------------------------------------------------------

class TestIngestAssetUseCase:
    def _make_use_case(
        self,
        chunker=_success_chunker,
        storage=None,
    ) -> tuple[IngestAssetUseCase, InMemoryIdempotencyStore, InMemoryChunkStore]:
        idempotency = InMemoryIdempotencyStore()
        chunk_store = InMemoryChunkStore()
        asset_storage = storage or _StubStorage()
        use_case = IngestAssetUseCase(
            idempotency_store=idempotency,
            asset_storage=asset_storage,
            chunk_store=chunk_store,
            chunker=chunker,
        )
        return use_case, idempotency, chunk_store

    def test_happy_path_returns_ingest_result(self):
        use_case, _, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert isinstance(result, IngestResult)
        assert result.asset_id == ASSET_ID
        assert result.tenant_id == TENANT_ID
        assert result.chunk_count == 3
        assert result.chunk_strategy == STRATEGY
        assert result.task_id == TASK_ID

    def test_happy_path_marks_asset_as_processed(self):
        use_case, idempotency, _ = self._make_use_case()
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert idempotency.is_processed(ASSET_ID, TENANT_ID) is True

    def test_happy_path_persists_chunks_in_store(self):
        use_case, _, chunk_store = self._make_use_case()
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        chunks = chunk_store.find_by_asset(ASSET_ID, TENANT_ID)
        assert len(chunks) == 3

    def test_happy_path_duration_ms_is_non_negative(self):
        use_case, _, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.duration_ms >= 0

    def test_already_processed_raises_asset_already_processed_error(self):
        use_case, idempotency, _ = self._make_use_case()
        idempotency.mark_processed(ASSET_ID, TENANT_ID)
        with pytest.raises(AssetAlreadyProcessedError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_storage_failure_propagates_without_calling_chunk_store(self):
        use_case, _, chunk_store = self._make_use_case(storage=_MissingStorage())
        with pytest.raises(FileNotFoundError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        assert chunk_store.find_by_asset(ASSET_ID, TENANT_ID) == []

    def test_chunker_failure_propagates_without_marking_processed(self):
        use_case, idempotency, _ = self._make_use_case(chunker=_failing_chunker)
        with pytest.raises(RuntimeError, match="chunker simulated failure"):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        assert idempotency.is_processed(ASSET_ID, TENANT_ID) is False

    def test_chunker_receives_content_and_strategy(self):
        received: list[tuple] = []

        def recording_chunker(content: bytes, strategy: str) -> list[Chunk]:
            received.append((content, strategy))
            return [Chunk(text="x")]

        use_case, _, _ = self._make_use_case(chunker=recording_chunker)
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy="bpmn", task_id=TASK_ID,
        )
        assert received == [(CONTENT, "bpmn")]

    def test_different_tenants_same_asset_id_are_independent(self):
        use_case, idempotency, _ = self._make_use_case()
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert idempotency.is_processed(ASSET_ID, OTHER_TENANT) is False
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=OTHER_TENANT,
            chunk_strategy=STRATEGY, task_id="task-2",
        )
        assert result.tenant_id == OTHER_TENANT
