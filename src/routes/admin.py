"""
admin.py — Administrative routes: Prometheus metrics scrape endpoint and job status.

Routes defined here:
    GET /metrics          — Prometheus text exposition format (Sprint 1)
    GET /admin/jobs/{id}  — Async job status polling (Sprint 6 stub)

Prometheus scraping:
    The /metrics endpoint must NOT be protected by AuthMiddleware.
    Add "/metrics" to AuthMiddleware._PUBLIC_PATHS (already done in Sprint 1).
    Content-Type returned: value of prometheus_client.CONTENT_TYPE_LATEST
    (e.g. text/plain; version=0.0.4 or version=1.0.0 depending on library).
    Prometheus server accepts both versions.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

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
        "Sprint 6 will wire this to the real Celery result backend. "
        "Sprint 1 stub always returns 'unknown'."
    ),
)
async def get_job_status(job_id: str) -> dict:
    """Return the status of a background job by job_id.

    Sprint 6 full implementation will query Celery result backend
    and return {status, result, error} from MongoDB failed_tasks collection.
    """
    logger.info("admin.job_status_requested", job_id=job_id, stub=True)
    # Sprint 6: replace with real Celery AsyncResult lookup
    return {
        "job_id": job_id,
        "status": "unknown",
        "result": None,
        "error": None,
        "stub": True,
    }


__all__ = ["router"]
