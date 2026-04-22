"""
Integration tests — Sprint 6 Task 4
Covers: embed_asset Celery task (retry policy, dead-letter, idempotency, metrics)

Strategy
--------
- Celery runs in EAGER mode (task_always_eager=True) — no real broker needed.
  In eager mode retries execute synchronously, so the full retry chain completes
  within a single test call.
- Dependencies (use case, dead-letter repo, vector store) are injected via
  a test-specific DI container, monkeypatched onto get_worker_container().
- Prometheus counters are read directly from the metric objects after each test.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.domain.chunk import Chunk
from src.infrastructure.di.container import DIContainer
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.infrastructure.workers.celery_app import celery_app
from src.infrastructure.workers.dead_letter_repository import InMemoryDeadLetterRepository
from src.infrastructure.workers.tasks.embed_task import (
    BASE_RETRY_DELAY_SECONDS,
    MAX_RETRIES,
    MAX_RETRY_DELAY_SECONDS,
    TASK_NAME,
    embed_asset,
)
from src.observability.prometheus_metrics import (
    EMBED_TASK_DURATION,
    EMBED_TASKS_DISPATCHED,
    EMBED_TASKS_FAILED,
)
from src.use_cases.tasks.embed_asset_use_case import EmbedAssetUseCase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASSET_ID = "doc-embed-001"
TENANT_ID = "tenant-ferza"
STRATEGY = "sop"

_CHUNKS = [
    Chunk(text="Article 1", metadata={"section": "scope"}),
    Chunk(text="Article 2", metadata={"section": "definitions"}),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_test_container(
    chunker,
    embedder=None,
    dead_letter_repo: InMemoryDeadLetterRepository | None = None,
    vector_store: InMemoryVectorStore | None = None,
) -> DIContainer:
    """Build a minimal DI container wiring embed_use_case."""
    dl_repo = dead_letter_repo or InMemoryDeadLetterRepository()
    vs = vector_store or InMemoryVectorStore()
    _embedder = embedder or (lambda chunks, a, t: len(chunks))
    use_case = EmbedAssetUseCase(
        vector_store=vs,
        chunker=chunker,
        embedder=_embedder,
    )
    container = DIContainer()
    container.register("dead_letter_repository", dl_repo)
    container.register("embed_use_case", use_case)
    return container


def _read_counter(metric, task_name: str = TASK_NAME) -> float:
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
    """
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestEmbedAssetHappyPath:
    def test_successful_embed_returns_success_status(self):
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["status"] == "success"

    def test_successful_embed_returns_asset_id_and_tenant_id(self):
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["asset_id"] == ASSET_ID
        assert result["tenant_id"] == TENANT_ID

    def test_successful_embed_returns_correct_vector_count(self):
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["vector_count"] == len(_CHUNKS)

    def test_successful_embed_returns_chunk_strategy(self):
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, "bpmn"]).get()
        assert result["chunk_strategy"] == "bpmn"

    def test_successful_embed_includes_duration_ms(self):
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert "duration_ms" in result
        assert result["duration_ms"] >= 0

    def test_successful_embed_includes_task_id(self):
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert "task_id" in result
        assert result["task_id"]

    def test_successful_embed_result_is_json_serialisable(self):
        import json
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        json.dumps(result)

    def test_default_chunk_strategy_is_sop(self):
        received_strategy: list[str] = []

        def recording_chunker(a: str, t: str, s: str) -> list[Chunk]:
            received_strategy.append(s)
            return _CHUNKS

        container = _build_test_container(chunker=recording_chunker)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID]).get()
        assert received_strategy == ["sop"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestEmbedAssetIdempotency:
    def test_second_call_same_asset_returns_skipped(self):
        vs = InMemoryVectorStore()
        vs.save_vectors(ASSET_ID, TENANT_ID, 5)
        container = _build_test_container(
            chunker=lambda a, t, s: _CHUNKS,
            vector_store=vs,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["status"] == "skipped"
        assert result["reason"] == "already_embedded"

    def test_skipped_result_contains_asset_and_tenant(self):
        vs = InMemoryVectorStore()
        vs.save_vectors(ASSET_ID, TENANT_ID, 5)
        container = _build_test_container(
            chunker=lambda a, t, s: _CHUNKS,
            vector_store=vs,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["asset_id"] == ASSET_ID
        assert result["tenant_id"] == TENANT_ID

    def test_different_tenant_same_asset_not_skipped(self):
        """Tenant isolation: embedding for tenant-A must not block tenant-B."""
        vs = InMemoryVectorStore()
        vs.save_vectors(ASSET_ID, TENANT_ID, 5)
        container = _build_test_container(
            chunker=lambda a, t, s: _CHUNKS,
            vector_store=vs,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, "tenant-acme", STRATEGY]).get()
        assert result["status"] == "success"

    def test_first_call_saves_vectors_in_store(self):
        vs = InMemoryVectorStore()
        container = _build_test_container(
            chunker=lambda a, t, s: _CHUNKS,
            vector_store=vs,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert vs.has_vectors(ASSET_ID, TENANT_ID) is True
        assert vs.count(ASSET_ID, TENANT_ID) == len(_CHUNKS)


# ---------------------------------------------------------------------------
# Retry policy and dead-letter
# ---------------------------------------------------------------------------

class TestEmbedAssetRetryPolicy:
    def test_failing_task_retries_exactly_max_retries_times(self):
        """Chunker called MAX_RETRIES + 1 times total (1 original + 3 retries)."""
        call_count = [0]

        def counting_failing_chunker(a: str, t: str, s: str) -> list[Chunk]:
            call_count[0] += 1
            raise RuntimeError("permanent failure")

        container = _build_test_container(chunker=counting_failing_chunker)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert call_count[0] == MAX_RETRIES + 1

    def test_failing_task_writes_exactly_one_dead_letter_entry(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda a, t, s: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert dl_repo.count() == 1

    def test_dead_letter_entry_has_correct_asset_and_tenant(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda a, t, s: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.asset_id == ASSET_ID
        assert entry.tenant_id == TENANT_ID

    def test_dead_letter_entry_has_correct_retry_count(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda a, t, s: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.retry_count == MAX_RETRIES

    def test_dead_letter_entry_has_exception_type_and_message(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda a, t, s: (_ for _ in ()).throw(RuntimeError("embed_boom")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.exception_type == "RuntimeError"
        assert "embed_boom" in entry.exception_message

    def test_dead_letter_entry_has_task_name(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda a, t, s: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.task_name == TASK_NAME

    def test_dead_letter_entry_args_contain_asset_and_tenant(self):
        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda a, t, s: (_ for _ in ()).throw(RuntimeError("fail")),
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        entry = dl_repo.get_all()[0]
        assert entry.args["asset_id"] == ASSET_ID
        assert entry.args["tenant_id"] == TENANT_ID

    def test_vectors_not_saved_after_full_retry_exhaustion(self):
        vs = InMemoryVectorStore()
        container = _build_test_container(
            chunker=lambda a, t, s: (_ for _ in ()).throw(RuntimeError("fail")),
            vector_store=vs,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert vs.has_vectors(ASSET_ID, TENANT_ID) is False

    def test_transient_failure_then_success_writes_no_dead_letter(self):
        """Task succeeds before retries exhausted — no dead-letter entry."""
        dl_repo = InMemoryDeadLetterRepository()
        attempts = [0]

        def fails_once_then_succeeds(a: str, t: str, s: str) -> list[Chunk]:
            attempts[0] += 1
            if attempts[0] == 1:
                raise RuntimeError("transient")
            return _CHUNKS

        container = _build_test_container(
            chunker=fails_once_then_succeeds,
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert result["status"] == "success"
        assert dl_repo.count() == 0

    def test_embedder_failure_triggers_retry_chain(self):
        """Embedder raising must also go through the retry/dead-letter path."""
        call_count = [0]

        def failing_embedder(chunks: list[Chunk], a: str, t: str) -> int:
            call_count[0] += 1
            raise RuntimeError("embedder down")

        dl_repo = InMemoryDeadLetterRepository()
        container = _build_test_container(
            chunker=lambda a, t, s: _CHUNKS,
            embedder=failing_embedder,
            dead_letter_repo=dl_repo,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        assert call_count[0] == MAX_RETRIES + 1
        assert dl_repo.count() == 1


# ---------------------------------------------------------------------------
# Exponential backoff countdown values
# ---------------------------------------------------------------------------

class TestExponentialBackoffCountdown:
    def test_first_retry_countdown_is_30_seconds(self):
        countdown = min(BASE_RETRY_DELAY_SECONDS * (2 ** 0), MAX_RETRY_DELAY_SECONDS)
        assert countdown == 30

    def test_second_retry_countdown_is_60_seconds(self):
        countdown = min(BASE_RETRY_DELAY_SECONDS * (2 ** 1), MAX_RETRY_DELAY_SECONDS)
        assert countdown == 60

    def test_third_retry_countdown_is_120_seconds(self):
        countdown = min(BASE_RETRY_DELAY_SECONDS * (2 ** 2), MAX_RETRY_DELAY_SECONDS)
        assert countdown == 120

    def test_countdown_capped_at_max_delay(self):
        countdown = min(BASE_RETRY_DELAY_SECONDS * (2 ** 20), MAX_RETRY_DELAY_SECONDS)
        assert countdown == MAX_RETRY_DELAY_SECONDS


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

class TestEmbedAssetMetrics:
    def test_dispatched_counter_increments_on_success(self):
        before = _read_counter(EMBED_TASKS_DISPATCHED)
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert _read_counter(EMBED_TASKS_DISPATCHED) > before

    def test_dispatched_counter_increments_on_skipped(self):
        """Dispatched is incremented even when the task returns skipped."""
        vs = InMemoryVectorStore()
        vs.save_vectors(ASSET_ID, TENANT_ID, 5)
        before = _read_counter(EMBED_TASKS_DISPATCHED)
        container = _build_test_container(
            chunker=lambda a, t, s: _CHUNKS,
            vector_store=vs,
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert _read_counter(EMBED_TASKS_DISPATCHED) > before

    def test_failed_counter_increments_after_retry_exhaustion(self):
        before = _read_counter(EMBED_TASKS_FAILED)
        container = _build_test_container(
            chunker=lambda a, t, s: (_ for _ in ()).throw(RuntimeError("fail"))
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert _read_counter(EMBED_TASKS_FAILED) > before

    def test_failed_counter_not_incremented_on_success(self):
        before = _read_counter(EMBED_TASKS_FAILED)
        container = _build_test_container(chunker=lambda a, t, s: _CHUNKS)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container", return_value=container):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert _read_counter(EMBED_TASKS_FAILED) == before


# ---------------------------------------------------------------------------
# Worker container validation — embed_use_case is a required port
# ---------------------------------------------------------------------------

class TestEmbedWorkerContainerValidation:
    def test_validate_worker_passes_when_embed_use_case_bound(self):
        container = DIContainer()
        container.register("dead_letter_repository", object())
        container.register("idempotency_store", object())
        container.register("ingest_use_case", object())
        container.register("embed_use_case", object())
        container.validate_worker()  # must not raise

    def test_validate_worker_raises_when_embed_use_case_missing(self):
        from src.infrastructure.di.container import MissingBindingError
        container = DIContainer()
        container.register("dead_letter_repository", object())
        container.register("idempotency_store", object())
        container.register("ingest_use_case", object())
        # embed_use_case intentionally omitted
        with pytest.raises(MissingBindingError, match="embed_use_case"):
            container.validate_worker()
