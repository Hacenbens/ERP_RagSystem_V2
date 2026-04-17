"""
Unit tests — Sprint 6 Task 1
Covers: domain models, InMemory repositories, IngestAssetUseCase

All tests are pure in-memory — no Celery, no MongoDB, no I/O.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.domain.ingest import FailedTaskEntry, IngestResult
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


def _success_chunker(asset_id: str, tenant_id: str, strategy: str) -> int:
    """Always returns 5 chunks — simulates a working chunker."""
    return 5


def _failing_chunker(asset_id: str, tenant_id: str, strategy: str) -> int:
    """Always raises — simulates a broken chunker."""
    raise RuntimeError("chunker simulated failure")


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
# IngestAssetUseCase
# ---------------------------------------------------------------------------

class TestIngestAssetUseCase:
    def _make_use_case(self, chunker=_success_chunker) -> tuple[IngestAssetUseCase, InMemoryIdempotencyStore]:
        store = InMemoryIdempotencyStore()
        use_case = IngestAssetUseCase(idempotency_store=store, chunker=chunker)
        return use_case, store

    def test_happy_path_returns_ingest_result(self):
        use_case, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID,
            tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY,
            task_id=TASK_ID,
        )
        assert isinstance(result, IngestResult)
        assert result.asset_id == ASSET_ID
        assert result.tenant_id == TENANT_ID
        assert result.chunk_count == 5
        assert result.chunk_strategy == STRATEGY
        assert result.task_id == TASK_ID

    def test_happy_path_marks_asset_as_processed(self):
        use_case, store = self._make_use_case()
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert store.is_processed(ASSET_ID, TENANT_ID) is True

    def test_happy_path_duration_ms_is_non_negative(self):
        use_case, _ = self._make_use_case()
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.duration_ms >= 0

    def test_already_processed_raises_asset_already_processed_error(self):
        use_case, store = self._make_use_case()
        store.mark_processed(ASSET_ID, TENANT_ID)
        with pytest.raises(AssetAlreadyProcessedError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_already_processed_error_message_contains_asset_id(self):
        use_case, store = self._make_use_case()
        store.mark_processed(ASSET_ID, TENANT_ID)
        with pytest.raises(AssetAlreadyProcessedError, match=ASSET_ID):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )

    def test_chunker_failure_propagates_without_marking_processed(self):
        use_case, store = self._make_use_case(chunker=_failing_chunker)
        with pytest.raises(RuntimeError, match="chunker simulated failure"):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        # Asset must NOT be marked processed after a failure
        assert store.is_processed(ASSET_ID, TENANT_ID) is False

    def test_different_tenants_same_asset_id_processed_independently(self):
        """Two tenants with the same asset_id must not interfere with each other."""
        use_case, store = self._make_use_case()
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        # The same asset_id for another tenant is NOT yet processed
        assert store.is_processed(ASSET_ID, OTHER_TENANT) is False

        # The second tenant can ingest their copy independently
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=OTHER_TENANT,
            chunk_strategy=STRATEGY, task_id="task-2",
        )
        assert result.tenant_id == OTHER_TENANT

    def test_chunker_receives_correct_arguments(self):
        received: list[tuple[str, str, str]] = []

        def recording_chunker(asset_id: str, tenant_id: str, strategy: str) -> int:
            received.append((asset_id, tenant_id, strategy))
            return 3

        use_case, _ = self._make_use_case(chunker=recording_chunker)
        use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy="bpmn", task_id=TASK_ID,
        )
        assert received == [(ASSET_ID, TENANT_ID, "bpmn")]

    def test_second_call_after_failure_can_succeed(self):
        """After a chunker failure the asset is not marked — a retry can succeed."""
        attempts = [0]

        def first_fails_then_succeeds(asset_id: str, tenant_id: str, strategy: str) -> int:
            attempts[0] += 1
            if attempts[0] == 1:
                raise RuntimeError("transient error")
            return 4

        use_case, store = self._make_use_case(chunker=first_fails_then_succeeds)

        with pytest.raises(RuntimeError):
            use_case.execute(
                asset_id=ASSET_ID, tenant_id=TENANT_ID,
                chunk_strategy=STRATEGY, task_id=TASK_ID,
            )
        # First call failed — asset NOT marked
        assert store.is_processed(ASSET_ID, TENANT_ID) is False

        # Second call succeeds
        result = use_case.execute(
            asset_id=ASSET_ID, tenant_id=TENANT_ID,
            chunk_strategy=STRATEGY, task_id=TASK_ID,
        )
        assert result.chunk_count == 4
        assert store.is_processed(ASSET_ID, TENANT_ID) is True
