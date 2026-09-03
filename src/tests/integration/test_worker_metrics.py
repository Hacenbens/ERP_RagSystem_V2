"""
Integration tests — Sprint 6 Task 6
Covers: Prometheus /metrics endpoint health + all Sprint 6 worker metrics

Strategy
--------
- A bare FastAPI app mounts only the admin router so tests focus on the
  metrics endpoint contract without the full middleware stack.
- Celery runs in EAGER mode so ingest_asset and embed_asset execute
  synchronously, letting us assert counter changes in-process.
- All metric assertions read directly from the global REGISTRY so results
  are cross-checked against both the in-process counters AND the scraped
  /metrics text — two independent verification paths.
- Worker containers are injected via monkeypatching to avoid real I/O.

What is verified
----------------
  1. /metrics returns 200, correct Content-Type, valid Prometheus text
  2. All Sprint 6 metric names are declared in the REGISTRY
  3. WORKER_TASKS_DISPATCHED increments after a real ingest_asset dispatch
  4. WORKER_TASKS_FAILED increments after ingest retry exhaustion
  5. EMBED_TASKS_DISPATCHED increments after a real embed_asset dispatch
  6. EMBED_TASKS_FAILED increments after embed retry exhaustion
  7. EMBED_TASK_DURATION bucket family appears in /metrics text after dispatch
  8. Each metric name appears in /metrics text output
  9. GET /admin/jobs/{id} endpoint is reachable and returns the contract shape
"""
from __future__ import annotations

from collections.abc import Iterator

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.domain.chunk import Chunk
from src.domain.ports.asset_storage_port import AssetStoragePort
from src.domain.ports.chunk_store_port import ChunkStorePort
from src.domain.ports.embedding_port import EmbeddingPort
from src.infrastructure.di.container import DIContainer
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.infrastructure.workers.celery_app import celery_app
from src.infrastructure.workers.dead_letter_repository import InMemoryDeadLetterRepository
from src.infrastructure.workers.idempotency_store import InMemoryIdempotencyStore
from src.infrastructure.workers.tasks.embed_task import embed_asset
from src.infrastructure.workers.tasks.ingest_task import ingest_asset
from src.observability.prometheus_metrics import (
    EMBED_TASKS_DISPATCHED,
    EMBED_TASKS_FAILED,
    WORKER_TASKS_DISPATCHED,
    WORKER_TASKS_FAILED,
)
from src.routes.admin import router as admin_router
from src.use_cases.tasks.embed_asset_use_case import EmbedAssetUseCase
from src.use_cases.tasks.ingest_asset_use_case import IngestAssetUseCase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASSET_ID = "metrics-asset-001"
TENANT_ID = "tenant-metrics"
STRATEGY = "sop"

_CHUNKS = [
    Chunk(text="Section 1", metadata={"section": "s1"}),
    Chunk(text="Section 2", metadata={"section": "s2"}),
]

# All Sprint 6 metric base names that MUST appear in /metrics output
SPRINT6_METRIC_NAMES = [
    "erp_rag_worker_tasks_dispatched_total",
    "erp_rag_worker_tasks_failed_total",
    "erp_rag_worker_task_duration_seconds",
    "erp_rag_embed_tasks_dispatched_total",
    "erp_rag_embed_tasks_failed_total",
    "erp_rag_embed_task_duration_seconds",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubAssetStorage(AssetStoragePort):
    def save_bytes(self, tenant_id, asset_id, filename, content):
        return f"{tenant_id}/{asset_id}/{filename}"
    def read_bytes(self, tenant_id, storage_key):
        return b"stub content"
    def delete_bytes(self, tenant_id, storage_key):
        pass


class _StubChunkStore(ChunkStorePort):
    def __init__(self, chunks=None):
        self._chunks = list(chunks) if chunks is not None else list(_CHUNKS)
    def save_chunks(self, asset_id, tenant_id, chunks):
        return len(chunks)
    def find_by_asset(self, asset_id, tenant_id):
        return list(self._chunks)
    def delete_by_asset(self, asset_id, tenant_id):
        return 0


class _FailingChunkStore(ChunkStorePort):
    def save_chunks(self, asset_id, tenant_id, chunks):
        return 0
    def find_by_asset(self, asset_id, tenant_id):
        raise RuntimeError("fail")
    def delete_by_asset(self, asset_id, tenant_id):
        return 0


class _StubEmbeddingPort(EmbeddingPort):
    def embed(self, text):
        return [0.0] * 768


def _counter_value(metric, task_name: str) -> float:
    try:
        return metric.labels(task_name=task_name)._value.get()
    except Exception:
        return 0.0


def _build_ingest_container(
    chunker=None,
    dead_letter_repo=None,
    asset_storage=None,
    chunk_store=None,
) -> DIContainer:
    dl_repo = dead_letter_repo or InMemoryDeadLetterRepository()
    id_store = InMemoryIdempotencyStore()
    _storage = asset_storage or _StubAssetStorage()
    _chunk_store = chunk_store or _StubChunkStore()
    _chunker = chunker or (lambda content, strategy: [Chunk(text=f"c{i}") for i in range(3)])
    use_case = IngestAssetUseCase(
        idempotency_store=id_store,
        asset_storage=_storage,
        chunk_store=_chunk_store,
        chunker=_chunker,
    )
    c = DIContainer()
    c.register("dead_letter_repository", dl_repo)
    c.register("idempotency_store", id_store)
    c.register("ingest_use_case", use_case)
    c.register("embed_use_case", object())
    return c


def _build_embed_container(
    dead_letter_repo=None,
    vector_store=None,
    chunk_store=None,
    embedding_port=None,
) -> DIContainer:
    dl_repo = dead_letter_repo or InMemoryDeadLetterRepository()
    vs = vector_store or InMemoryVectorStore()
    _chunk_store = chunk_store or _StubChunkStore()
    _embedding_port = embedding_port or _StubEmbeddingPort()
    use_case = EmbedAssetUseCase(
        vector_store=vs,
        chunk_store=_chunk_store,
        embedding_port=_embedding_port,
    )
    c = DIContainer()
    c.register("dead_letter_repository", dl_repo)
    c.register("embed_use_case", use_case)
    c.register("ingest_use_case", object())
    c.register("idempotency_store", object())
    return c


def _mock_ar(state: str, result=None) -> MagicMock:
    ar = MagicMock()
    ar.state = state
    ar.result = result
    return ar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def metrics_client() -> Iterator[TestClient]:
    """Bare FastAPI app with only the admin router — no auth middleware."""
    app = FastAPI()
    app.include_router(admin_router)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def celery_eager_mode():
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False


# ---------------------------------------------------------------------------
# /metrics endpoint health
# ---------------------------------------------------------------------------

class TestMetricsEndpointHealth:
    def test_get_metrics_returns_200(self, metrics_client):
        assert metrics_client.get("/metrics").status_code == 200

    def test_get_metrics_content_type_is_prometheus_format(self, metrics_client):
        from prometheus_client import CONTENT_TYPE_LATEST
        resp = metrics_client.get("/metrics")
        assert resp.headers["content-type"] == CONTENT_TYPE_LATEST

    def test_get_metrics_body_contains_help_lines(self, metrics_client):
        text = metrics_client.get("/metrics").text
        assert any(line.startswith("# HELP") for line in text.splitlines())

    def test_get_metrics_body_contains_type_lines(self, metrics_client):
        text = metrics_client.get("/metrics").text
        assert any(line.startswith("# TYPE") for line in text.splitlines())

    def test_get_metrics_body_is_not_json(self, metrics_client):
        import json
        with pytest.raises(Exception):
            json.loads(metrics_client.get("/metrics").text)

    def test_get_metrics_accessible_without_auth_token(self, metrics_client):
        """Prometheus scraper must not require a Bearer token."""
        resp = metrics_client.get("/metrics")  # no Authorization header
        assert resp.status_code == 200

    def test_get_metrics_contains_erp_rag_lines(self, metrics_client):
        text = metrics_client.get("/metrics").text
        erp_lines = [line for line in text.splitlines() if "erp_rag_" in line]
        assert len(erp_lines) > 0


# ---------------------------------------------------------------------------
# Sprint 6 metric names declared in registry and exposed on /metrics
# ---------------------------------------------------------------------------

class TestSprint6MetricsDeclared:
    """All Sprint 6 metric families must be registered before any task runs."""

    @pytest.mark.parametrize("metric_name", SPRINT6_METRIC_NAMES)
    def test_metric_registered_in_prometheus_registry(self, metric_name):
        # _names_to_collectors holds all declared metric names regardless of
        # whether any label set has been observed yet (unlike collect() samples).
        assert metric_name in REGISTRY._names_to_collectors, (
            f"Metric '{metric_name}' not found in REGISTRY._names_to_collectors"
        )

    @pytest.mark.parametrize("metric_name", SPRINT6_METRIC_NAMES)
    def test_metric_appears_in_metrics_endpoint_text(self, metrics_client, metric_name):
        text = metrics_client.get("/metrics").text
        assert metric_name in text, (
            f"'{metric_name}' not found in /metrics text output"
        )


# ---------------------------------------------------------------------------
# WORKER metrics — ingest_asset task
# ---------------------------------------------------------------------------

class TestWorkerMetricsAfterIngestDispatch:
    def test_worker_dispatched_counter_increments_on_success(self):
        from src.infrastructure.workers.tasks.ingest_task import TASK_NAME
        before = _counter_value(WORKER_TASKS_DISPATCHED, TASK_NAME)
        container = _build_ingest_container()
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container",
                   return_value=container):
            ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert _counter_value(WORKER_TASKS_DISPATCHED, TASK_NAME) > before

    def test_worker_dispatched_counter_appears_in_metrics_text(self, metrics_client):
        container = _build_ingest_container()
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container",
                   return_value=container):
            ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert "erp_rag_worker_tasks_dispatched_total" in metrics_client.get("/metrics").text

    def test_worker_failed_counter_increments_after_retry_exhaustion(self):
        from src.infrastructure.workers.tasks.ingest_task import TASK_NAME
        before = _counter_value(WORKER_TASKS_FAILED, TASK_NAME)
        container = _build_ingest_container(
            chunker=lambda content, strategy: (_ for _ in ()).throw(RuntimeError("fail"))
        )
        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container",
                   return_value=container):
            with pytest.raises(Exception):
                ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert _counter_value(WORKER_TASKS_FAILED, TASK_NAME) > before

    def test_worker_failed_counter_appears_in_metrics_text(self, metrics_client):
        assert "erp_rag_worker_tasks_failed_total" in metrics_client.get("/metrics").text

    def test_worker_duration_histogram_appears_in_metrics_text(self, metrics_client):
        assert "erp_rag_worker_task_duration_seconds" in metrics_client.get("/metrics").text


# ---------------------------------------------------------------------------
# EMBED metrics — embed_asset task
# ---------------------------------------------------------------------------

class TestEmbedMetricsAfterEmbedDispatch:
    def test_embed_dispatched_counter_increments_on_success(self):
        from src.infrastructure.workers.tasks.embed_task import TASK_NAME
        before = _counter_value(EMBED_TASKS_DISPATCHED, TASK_NAME)
        container = _build_embed_container()
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container",
                   return_value=container):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert _counter_value(EMBED_TASKS_DISPATCHED, TASK_NAME) > before

    def test_embed_dispatched_counter_appears_in_metrics_text(self, metrics_client):
        container = _build_embed_container()
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container",
                   return_value=container):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert "erp_rag_embed_tasks_dispatched_total" in metrics_client.get("/metrics").text

    def test_embed_failed_counter_increments_after_retry_exhaustion(self):
        from src.infrastructure.workers.tasks.embed_task import TASK_NAME
        before = _counter_value(EMBED_TASKS_FAILED, TASK_NAME)
        container = _build_embed_container(
            chunk_store=_FailingChunkStore()
        )
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container",
                   return_value=container):
            with pytest.raises(Exception):
                embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert _counter_value(EMBED_TASKS_FAILED, TASK_NAME) > before

    def test_embed_failed_counter_appears_in_metrics_text(self, metrics_client):
        assert "erp_rag_embed_tasks_failed_total" in metrics_client.get("/metrics").text

    def test_embed_duration_histogram_sum_recorded_after_dispatch(self):
        from src.infrastructure.workers.tasks.embed_task import TASK_NAME
        container = _build_embed_container()
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container",
                   return_value=container):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        found = False
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if (sample.name == "erp_rag_embed_task_duration_seconds_sum"
                        and sample.labels.get("task_name") == TASK_NAME):
                    assert sample.value >= 0
                    found = True
        assert found, "erp_rag_embed_task_duration_seconds_sum not found in REGISTRY"

    def test_embed_duration_histogram_appears_in_metrics_text(self, metrics_client):
        assert "erp_rag_embed_task_duration_seconds" in metrics_client.get("/metrics").text

    def test_embed_dispatched_increments_even_on_already_embedded(self):
        """dispatched counter fires before the idempotency guard runs."""
        from src.infrastructure.workers.tasks.embed_task import TASK_NAME
        vs = InMemoryVectorStore()
        vs.save_vectors(ASSET_ID, TENANT_ID, 5)
        before = _counter_value(EMBED_TASKS_DISPATCHED, TASK_NAME)
        container = _build_embed_container(vector_store=vs)
        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container",
                   return_value=container):
            result = embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()
        assert result["status"] == "skipped"
        assert _counter_value(EMBED_TASKS_DISPATCHED, TASK_NAME) > before


# ---------------------------------------------------------------------------
# GET /admin/jobs/{job_id} endpoint health
# ---------------------------------------------------------------------------

class TestJobStatusEndpointHealth:
    def test_get_job_status_returns_200(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("PENDING")):
            resp = metrics_client.get("/admin/jobs/test-job-id")
        assert resp.status_code == 200

    def test_get_job_status_returns_json_content_type(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("PENDING")):
            resp = metrics_client.get("/admin/jobs/test-job-id")
        assert resp.headers["content-type"].startswith("application/json")

    def test_get_job_status_response_has_all_required_keys(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("PENDING")):
            body = metrics_client.get("/admin/jobs/test-job-id").json()
        for key in ("job_id", "status", "result", "error"):
            assert key in body, f"Missing required key: '{key}'"

    def test_get_job_status_echoes_job_id_from_path(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("PENDING")):
            body = metrics_client.get("/admin/jobs/my-unique-job-99").json()
        assert body["job_id"] == "my-unique-job-99"

    def test_get_job_status_pending_state(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("PENDING")):
            body = metrics_client.get("/admin/jobs/job-1").json()
        assert body["status"] == "PENDING"
        assert body["result"] is None
        assert body["error"] is None

    def test_get_job_status_started_state(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("STARTED")):
            body = metrics_client.get("/admin/jobs/job-2").json()
        assert body["status"] == "STARTED"

    def test_get_job_status_success_exposes_result_payload(self, metrics_client):
        payload = {"status": "success", "vector_count": 7, "asset_id": ASSET_ID}
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("SUCCESS", payload)):
            body = metrics_client.get("/admin/jobs/job-3").json()
        assert body["status"] == "SUCCESS"
        assert body["result"]["vector_count"] == 7
        assert body["error"] is None

    def test_get_job_status_failure_exposes_error_message(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("FAILURE", RuntimeError("chunker exploded"))):
            body = metrics_client.get("/admin/jobs/job-4").json()
        assert body["status"] == "FAILURE"
        assert "chunker exploded" in body["error"]
        assert body["result"] is None

    def test_get_job_status_retry_state(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("RETRY")):
            body = metrics_client.get("/admin/jobs/job-5").json()
        assert body["status"] == "RETRY"

    def test_get_job_status_revoked_state(self, metrics_client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("REVOKED")):
            body = metrics_client.get("/admin/jobs/job-6").json()
        assert body["status"] == "REVOKED"

    def test_get_job_status_stub_key_absent(self, metrics_client):
        """The Sprint 1 stub=True field must be gone."""
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_ar("PENDING")):
            body = metrics_client.get("/admin/jobs/job-7").json()
        assert "stub" not in body

    def test_get_job_status_queries_correct_job_id(self, metrics_client):
        """AsyncResult must be constructed with the path job_id, not a hardcoded value."""
        with patch("src.routes.admin.celery_app.AsyncResult") as mock_cls:
            mock_cls.return_value = _mock_ar("PENDING")
            metrics_client.get("/admin/jobs/specific-job-abc")
        mock_cls.assert_called_once_with("specific-job-abc")


# ---------------------------------------------------------------------------
# Cross-cutting: all Sprint 6 metrics appear in a single /metrics scrape
# ---------------------------------------------------------------------------

class TestAllSprint6MetricsInSingleScrape:
    def test_all_sprint6_metric_families_visible_after_both_tasks_dispatched(
        self, metrics_client
    ):
        """One /metrics call after dispatching both task types must expose all 6 families."""
        container_ingest = _build_ingest_container()
        container_embed = _build_embed_container()

        with patch("src.infrastructure.workers.tasks.ingest_task.get_worker_container",
                   return_value=container_ingest):
            ingest_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        with patch("src.infrastructure.workers.tasks.embed_task.get_worker_container",
                   return_value=container_embed):
            embed_asset.apply(args=[ASSET_ID, TENANT_ID, STRATEGY]).get()

        text = metrics_client.get("/metrics").text
        for name in SPRINT6_METRIC_NAMES:
            assert name in text, f"'{name}' missing from /metrics after task dispatch"
