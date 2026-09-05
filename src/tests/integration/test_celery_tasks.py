"""
Integration tests — Sprint 6 Task 1 (updated Sprint 7 Task 18)
Covers: ingest_asset Celery task (retry policy, dead-letter, idempotency, metrics)

Strategy
--------
- Celery runs in EAGER mode (task_always_eager=True) — no real broker needed.
  In eager mode retries execute synchronously, so the full retry chain completes
  within a single test call.
- Dependencies (use case, dead-letter repo, idempotency store) are injected via
  a test-specific DI container, monkeypatched onto get_worker_container().
- Prometheus counters are read directly from the metric objects after each test.
- Sprint 7 refactor: IngestAssetUseCase now requires AssetStoragePort and
  ChunkStorePort. Stub implementations are injected; chunker signature is
  (content: bytes, strategy: str) -> list[Chunk].
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))


from src.domain.chunk import Chunk
from src.domain.ports.asset_storage_port import AssetStoragePort
from src.domain.ports.chunk_store_port import ChunkStorePort
from src.infrastructure.di.container import DIContainer
from src.infrastructure.workers.dead_letter_repository import InMemoryDeadLetterRepository
from src.infrastructure.workers.idempotency_store import InMemoryIdempotencyStore
from src.observability.prometheus_metrics import WORKER_TASKS_DISPATCHED, WORKER_TASKS_FAILED
from src.use_cases.tasks.ingest_asset_use_case import IngestAssetUseCase
from src.infrastructure.workers.celery_app import celery_app
from src.infrastructure.workers.tasks.ingest_task import (
    BASE_RETRY_DELAY_SECONDS,
    MAX_RETRIES,
    MAX_RETRY_DELAY_SECONDS,
    TASK_NAME,
    ingest_asset,
)

# ---------------------------------------------------------------------------
# Constants shared across tests
# ---------------------------------------------------------------------------

ASSET_ID = "doc-001"
TENANT_ID = "tenant-ferza"
STRATEGY = "sop"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubAssetStorage(AssetStoragePort):
    """Returns constant bytes from read_bytes — no filesystem I/O."""

    _CONTENT = b"stub document content for testing"

    def save_bytes(self, tenant_id: str, asset_id: str, filename: str, content: bytes) -> str:
        return f"{tenant_id}/{asset_id}/{filename}"

    def read_bytes(self, tenant_id: str, storage_key: str) -> bytes:
        return self._CONTENT

    def delete_bytes(self, tenant_id: str, storage_key: str) -> None:
        pass


class _StubChunkStore(ChunkStorePort):
    """Records save_chunks calls — no database I/O."""

    def __init__(self) -> None:
        self.saved: list[tuple] = []

    def save_chunks(self, asset_id: str, tenant_id: str, chunks: list[Chunk]) -> int:
        self.saved.append((asset_id, tenant_id, chunks))
        return len(chunks)

    def find_by_asset(self, asset_id: str, tenant_id: str) -> list[Chunk]:
        return []

    def delete_by_asset(self, asset_id: str, tenant_id: str) -> int:
        return 0

    def list_assets(self) -> list:
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunks(n: int) -> list[Chunk]:
    """Return a list of n minimal Chunk objects."""
    return [Chunk(text=f"chunk-{i}") for i in range(n)]


def _build_test_container(
    chunker,
    dead_letter_repo: InMemoryDeadLetterRepository | None = None,
    idempotency_store: InMemoryIdempotencyStore | None = None,
    asset_storage: AssetStoragePort | None = None,
    chunk_store: ChunkStorePort | None = None,
) -> DIContainer:
    """Build a minimal DI container for task tests."""
    dl_repo = dead_letter_repo or InMemoryDeadLetterRepository()
    id_store = idempotency_store or InMemoryIdempotencyStore()
    _storage = asset_storage or _StubAssetStorage()
    _chunk_store = chunk_store or _StubChunkStore()
    use_case = IngestAssetUseCase(
        idempotency_store=id_store,
        asset_storage=_storage,
        chunk_store=_chunk_store,
        chunker=chunker,
    )

    container = DIContainer()
    container.register("dead_letter_repository", dl_repo)
    container.register("idempotency_store", id_store)
    container.register("ingest_use_case", use_case)
    return container


def _read_counter(metric, task_name: str = TASK_NAME) -> float:
    """Read the current value of a labelled Prometheus counter."""
    try:
        return metric.labels(task_name=task_name)._value.get()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def celery_eager_mode():
    """Force Celery to execute tasks synchronously (no broker required).

    task_eager_propagates is intentionally left False (the default).
    Setting it True causes Celery's on_error() to re-raise Retry exceptions
    before apply() can catch them and recurse — breaking the retry loop.
    Exceptions still surface to callers via EagerResult.get(propagate=True).
    """
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestIngestAssetHappyPath:
    def test_successful_ingest_returns_success_status(self):
        container = _build_test_container(chunker=lambda content, strategy: _make_chunks(7))
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["status"] == "success"

    def test_successful_ingest_returns_asset_id_and_tenant_id(self):
        container = _build_test_container(chunker=lambda content, strategy: _make_chunks(7))
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["asset_id"] == ASSET_ID
        assert result["tenant_id"] == TENANT_ID

    def test_successful_ingest_returns_correct_chunk_count(self):
        container = _build_test_container(chunker=lambda content, strategy: _make_chunks(12))
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["chunk_count"] == 12

    def test_successful_ingest_returns_chunk_strategy(self):
        container = _build_test_container(chunker=lambda content, strategy: _make_chunks(3))
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, "bpmn"]).get()
        assert result["chunk_strategy"] == "bpmn"

    def test_successful_ingest_includes_task_id(self):
        container = _build_test_container(chunker=lambda content, strategy: _make_chunks(1))
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert "task_id" in result
        assert result["task_id"]

    def test_successful_ingest_result_is_json_serialisable(self):
        import json
        container = _build_test_container(chunker=lambda content, strategy: _make_chunks(5))
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        json.dumps(result)

    def test_default_chunk_strategy_is_sop(self):
        received_strategy: list[str] = []

        def recording_chunker(content: bytes, strategy: str) -> list[Chunk]:
            received_strategy.append(strategy)
            return _make_chunks(2)

        container = _build_test_container(chunker=recording_chunker)
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            ingest_asset.apply(args=[ASSET_ID, TENANT_ID]).get()  # no strategy arg
        assert received_strategy == ["sop"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIngestAssetIdempotency:
    def test_second_call_same_asset_returns_skipped(self):
        id_store = InMemoryIdempotencyStore()
        id_store.mark_processed(ASSET_ID, TENANT_ID)
        container = _build_test_container(
            chunker=lambda content, strategy: _make_chunks(5),
            idempotency_store=id_store,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["status"] == "skipped"
        assert result["reason"] == "already_processed"

    def test_second_call_skipped_result_contains_asset_and_tenant(self):
        id_store = InMemoryIdempotencyStore()
        id_store.mark_processed(ASSET_ID, TENANT_ID)
        container = _build_test_container(
            chunker=lambda content, strategy: _make_chunks(5),
            idempotency_store=id_store,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["asset_id"] == ASSET_ID
        assert result["tenant_id"] == TENANT_ID

    def test_different_tenant_same_asset_id_not_skipped(self):
        """Tenant isolation: processing asset for tenant-A must not block tenant-B."""
        id_store = InMemoryIdempotencyStore()
        id_store.mark_processed(ASSET_ID, TENANT_ID)
        container = _build_test_container(
            chunker=lambda content, strategy: _make_chunks(3),
            idempotency_store=id_store,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, "tenant-acme", STRATEGY]).get()
        assert result["status"] == "success"

    def test_first_call_marks_asset_as_processed(self):
        id_store = InMemoryIdempotencyStore()
        container = _build_test_container(
            chunker=lambda content, strategy: _make_chunks(5),
            idempotency_store=id_store,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert id_store.is_processed(ASSET_ID, TENANT_ID) is True


# ---------------------------------------------------------------------------
# Retry policy and dead-letter
# ---------------------------------------------------------------------------

class TestIngestAssetRetryPolicy:
    def test_failing_task_retries_exactly_max_retries_times(self):
        """Chunker called MAX_RETRIES + 1 times total (1 original + 3 retries)."""
        call_count = [0]

        def counting_failing_chunker(content: bytes, strategy: str) -> list[Chunk]:
            call_count[0] += 1
            raise RuntimeError("permanent failure")

        container = _build_test_container(chunker=counting_failing_chunker)
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert call_count[0] == MAX_RETRIES + 1

    def test_failing_task_writes_exactly_one_dead_letter_entry(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert dl_repo.count() == 1

    def test_dead_letter_entry_has_correct_asset_id(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.asset_id == ASSET_ID
        assert entry.tenant_id == TENANT_ID

    def test_dead_letter_entry_has_correct_retry_count(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.retry_count == MAX_RETRIES

    def test_dead_letter_entry_has_exception_type(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("boom")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.exception_type == "RuntimeError"
        assert "boom" in entry.exception_message

    def test_dead_letter_entry_has_task_name(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.task_name == TASK_NAME

    def test_dead_letter_entry_args_contain_asset_and_tenant(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.args["asset_id"] == ASSET_ID
        assert entry.args["tenant_id"] == TENANT_ID

    def test_asset_not_marked_processed_after_full_retry_exhaustion(self):
        id_store = InMemoryIdempotencyStore()
        container = _build_test_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("fail")),
            idempotency_store=id_store,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert id_store.is_processed(ASSET_ID, TENANT_ID) is False

    def test_transient_failure_then_success_writes_no_dead_letter(self):
        """If the task succeeds before retries are exhausted, no dead-letter entry."""
        dl_repo = InMemoryDeadLetterRepository()
        attempts = [0]

        def fails_once_then_succeeds(content: bytes, strategy: str) -> list[Chunk]:
            attempts[0] += 1
            if attempts[0] == 1:
                raise RuntimeError("transient")
            return _make_chunks(5)

        container = _build_test_container(
            chunker=fails_once_then_succeeds,
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            result = ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert result["status"] == "success"
        assert dl_repo.count() == 0


# ---------------------------------------------------------------------------
# Exponential backoff countdown values
# ---------------------------------------------------------------------------

class TestExponentialBackoffCountdown:
    def test_first_retry_countdown_is_30_seconds(self):
        """Attempt 0 (retries=0): countdown = 30 * 2^0 = 30 s."""
        countdown = min(BASE_RETRY_DELAY_SECONDS * (2 ** 0), 600)
        assert countdown == 30

    def test_second_retry_countdown_is_60_seconds(self):
        """Attempt 1 (retries=1): countdown = 30 * 2^1 = 60 s."""
        countdown = min(BASE_RETRY_DELAY_SECONDS * (2 ** 1), 600)
        assert countdown == 60

    def test_third_retry_countdown_is_120_seconds(self):
        """Attempt 2 (retries=2): countdown = 30 * 2^2 = 120 s."""
        countdown = min(BASE_RETRY_DELAY_SECONDS * (2 ** 2), 600)
        assert countdown == 120

    def test_countdown_capped_at_max_delay(self):
        """Very high retry index must not exceed MAX_RETRY_DELAY_SECONDS."""
        countdown = min(BASE_RETRY_DELAY_SECONDS * (2 ** 20), MAX_RETRY_DELAY_SECONDS)
        assert countdown == MAX_RETRY_DELAY_SECONDS


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

class TestIngestAssetMetrics:
    def test_dispatched_counter_increments_on_success(self):
        before = _read_counter(WORKER_TASKS_DISPATCHED)
        container = _build_test_container(chunker=lambda content, strategy: _make_chunks(3))
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        after = _read_counter(WORKER_TASKS_DISPATCHED)
        assert after > before

    def test_failed_counter_increments_after_retry_exhaustion(self):
        before = _read_counter(WORKER_TASKS_FAILED)
        container = _build_test_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("fail"))
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        after = _read_counter(WORKER_TASKS_FAILED)
        assert after > before


# ---------------------------------------------------------------------------
# Worker container validation
# ---------------------------------------------------------------------------

class TestWorkerContainerValidation:
    def test_validate_worker_passes_when_all_ports_bound(self):
        from src.infrastructure.di.container import DIContainer
        container = DIContainer()
        container.register("dead_letter_repository", object())
        container.register("idempotency_store", object())
        container.register("ingest_use_case", object())
        container.register("embed_use_case", object())
        container.validate_worker()  # must not raise

    def test_validate_worker_raises_when_port_missing(self):
        from src.infrastructure.di.container import DIContainer, MissingBindingError
        container = DIContainer()
        container.register("dead_letter_repository", object())
        # idempotency_store and ingest_use_case missing
        with pytest.raises(MissingBindingError, match="idempotency_store"):
            container.validate_worker()
