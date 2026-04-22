"""
admin.py — Administrative routes: Prometheus metrics scrape endpoint and job status.

Routes defined here:
    GET /metrics          — Prometheus text exposition format (Sprint 1)
    GET /admin/jobs/{id}  — Async job status polling (Sprint 6)

Prometheus scraping:
    The /metrics endpoint must NOT be protected by AuthMiddleware.
    Add "/metrics" to AuthMiddleware._PUBLIC_PATHS (already done in Sprint 1).
    Content-Type returned: value of prometheus_client.CONTENT_TYPE_LATEST
    (e.g. text/plain; version=0.0.4 or version=1.0.0 depending on library).
    Prometheus server accepts both versions.

Job status states (from Celery):
    PENDING  — task queued but not yet picked up by a worker
    STARTED  — worker has picked up the task (requires task_track_started=True)
    SUCCESS  — task completed; result contains the return value
    FAILURE  — task failed after all retries; error contains the exception message
    RETRY    — task is being retried
    REVOKED  — task was cancelled
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.infrastructure.workers.celery_app import celery_app
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------------------
# GET /metrics — Prometheus scrape endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics",
    description=(
        "Exposes all registered Prometheus counters, histograms, and gauges "
        "in the standard text exposition format (version 0.0.4). "
        "Intended to be scraped by a Prometheus server — not for human consumption."
    ),
    include_in_schema=False,  # exclude from public OpenAPI docs
)
async def get_metrics() -> PlainTextResponse:
    """Return all Prometheus metrics in text exposition format."""
    logger.info("admin.metrics_scraped")
    payload = generate_latest()
    return PlainTextResponse(
        content=payload.decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


# ---------------------------------------------------------------------------
# GET /admin/jobs/{job_id} — Celery job status (Sprint 6 stub)
# ---------------------------------------------------------------------------

@router.get(
    "/admin/jobs/{job_id}",
    summary="Get async job status",
    description=(
        "Poll the status of a Celery background job. "
        "Returns the current state, the result payload on success, "
        "or the error message on failure."
    ),
)
async def get_job_status(job_id: str) -> dict:
    """Return the status of a background job by job_id.

    Queries the Celery result backend (Redis) via AsyncResult.
    States: PENDING | STARTED | SUCCESS | FAILURE | RETRY | REVOKED
    """
    async_result = celery_app.AsyncResult(job_id)
    state: str = async_result.state

    result_payload = None
    error_message = None

    if state == "SUCCESS":
        result_payload = async_result.result
    elif state == "FAILURE":
        exc = async_result.result  # holds the exception on failure
        error_message = str(exc) if exc is not None else "unknown error"

    logger.info(
        "admin.job_status_requested",
        job_id=job_id,
        state=state,
    )

    return {
        "job_id": job_id,
        "status": state,
        "result": result_payload,
        "error": error_message,
    }


__all__ = ["router"]
