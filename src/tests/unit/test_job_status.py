"""
Unit tests — Sprint 6 Task 5
Covers: GET /admin/jobs/{job_id} — real Celery AsyncResult lookup

Strategy
--------
- celery_app.AsyncResult is monkeypatched to return a MagicMock with
  the desired .state and .result — no Redis, no broker required.
- The admin router is mounted on a bare FastAPI app (no auth middleware)
  so tests focus exclusively on the job-status response contract.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.routes.admin import router as admin_router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

JOB_ID = "abc-123-task-id"


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _mock_async_result(state: str, result=None) -> MagicMock:
    """Return a MagicMock that looks like a Celery AsyncResult."""
    ar = MagicMock()
    ar.state = state
    ar.result = result
    return ar


# ---------------------------------------------------------------------------
# PENDING state
# ---------------------------------------------------------------------------

class TestJobStatusPending:
    def test_pending_returns_200(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            resp = client.get(f"/admin/jobs/{JOB_ID}")
        assert resp.status_code == 200

    def test_pending_status_field_is_pending(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["status"] == "PENDING"

    def test_pending_result_is_null(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["result"] is None

    def test_pending_error_is_null(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["error"] is None

    def test_pending_job_id_echoed(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["job_id"] == JOB_ID


# ---------------------------------------------------------------------------
# STARTED state
# ---------------------------------------------------------------------------

class TestJobStatusStarted:
    def test_started_status_field_is_started(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("STARTED")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["status"] == "STARTED"

    def test_started_result_is_null(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("STARTED")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["result"] is None

    def test_started_error_is_null(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("STARTED")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["error"] is None


# ---------------------------------------------------------------------------
# SUCCESS state
# ---------------------------------------------------------------------------

class TestJobStatusSuccess:
    _RESULT = {
        "status": "success",
        "asset_id": "doc-001",
        "tenant_id": "tenant-ferza",
        "vector_count": 5,
        "chunk_strategy": "sop",
        "duration_ms": 120.5,
        "task_id": JOB_ID,
    }

    def test_success_status_field_is_success(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("SUCCESS", self._RESULT)):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["status"] == "SUCCESS"

    def test_success_result_contains_task_payload(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("SUCCESS", self._RESULT)):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["result"]["asset_id"] == "doc-001"
        assert body["result"]["vector_count"] == 5

    def test_success_error_is_null(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("SUCCESS", self._RESULT)):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["error"] is None

    def test_success_skipped_result_also_serialised(self, client):
        skipped = {"status": "skipped", "reason": "already_embedded",
                   "asset_id": "doc-001", "tenant_id": "t", "task_id": JOB_ID}
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("SUCCESS", skipped)):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["status"] == "SUCCESS"
        assert body["result"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# FAILURE state
# ---------------------------------------------------------------------------

class TestJobStatusFailure:
    def test_failure_status_field_is_failure(self, client):
        exc = RuntimeError("chunker exploded")
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("FAILURE", exc)):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["status"] == "FAILURE"

    def test_failure_error_contains_exception_message(self, client):
        exc = RuntimeError("chunker exploded")
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("FAILURE", exc)):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert "chunker exploded" in body["error"]

    def test_failure_result_is_null(self, client):
        exc = RuntimeError("embedder down")
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("FAILURE", exc)):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["result"] is None

    def test_failure_with_none_exception_returns_unknown_error(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("FAILURE", None)):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["error"] == "unknown error"


# ---------------------------------------------------------------------------
# RETRY and REVOKED states
# ---------------------------------------------------------------------------

class TestJobStatusOtherStates:
    def test_retry_status_field_is_retry(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("RETRY")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["status"] == "RETRY"

    def test_retry_result_and_error_are_null(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("RETRY")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["result"] is None
        assert body["error"] is None

    def test_revoked_status_field_is_revoked(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("REVOKED")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert body["status"] == "REVOKED"


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------

class TestJobStatusResponseContract:
    def test_response_always_contains_job_id_key(self, client):
        for state in ("PENDING", "STARTED", "SUCCESS", "FAILURE", "RETRY", "REVOKED"):
            result = {"ok": True} if state == "SUCCESS" else None
            with patch("src.routes.admin.celery_app.AsyncResult",
                       return_value=_mock_async_result(state, result)):
                body = client.get(f"/admin/jobs/{JOB_ID}").json()
            assert "job_id" in body, f"job_id missing for state {state}"

    def test_response_always_contains_status_key(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert "status" in body

    def test_response_always_contains_result_key(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert "result" in body

    def test_response_always_contains_error_key(self, client):
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert "error" in body

    def test_stub_key_no_longer_present(self, client):
        """The stub=True field from Sprint 1 must be gone."""
        with patch("src.routes.admin.celery_app.AsyncResult",
                   return_value=_mock_async_result("PENDING")):
            body = client.get(f"/admin/jobs/{JOB_ID}").json()
        assert "stub" not in body

    def test_different_job_ids_query_their_own_async_result(self, client):
        """AsyncResult must be constructed with the actual job_id from the path."""
        with patch("src.routes.admin.celery_app.AsyncResult") as mock_ar_cls:
            mock_ar_cls.return_value = _mock_async_result("PENDING")
            client.get("/admin/jobs/job-alpha")
            mock_ar_cls.assert_called_once_with("job-alpha")
