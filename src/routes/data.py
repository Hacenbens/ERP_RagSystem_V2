"""
Data route — Sprint 7 Task 20
POST /api/assets/upload — accept a file upload, persist it, dispatch an ingest job.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from src.domain.models.upload_models import UploadResponse
from src.infrastructure.di.factory import build_container
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/assets", tags=["data"])


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def _get_asset_storage(request: Request):
    """Resolve AssetStoragePort from the app's DI container."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        container = build_container()
        request.app.state.container = container
    return container.get("asset_storage")


def _get_job_dispatcher(request: Request):
    """Resolve JobDispatcherPort from the app's DI container."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        container = build_container()
        request.app.state.container = container
    return container.get("job_dispatcher")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document asset and queue an ingestion job",
)
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    chunk_strategy: str = Form(default="sop"),
    storage=Depends(_get_asset_storage),
    dispatcher=Depends(_get_job_dispatcher),
) -> UploadResponse:
    """Accept a multipart file upload, save it, and dispatch a Celery ingest job.

    Requires a valid JWT (enforced by AuthMiddleware upstream).
    Returns HTTP 202 with asset_id and job_id for status polling.
    """
    tenant_id: str = getattr(request.state, "tenant_id", "")
    asset_id = str(uuid4())
    filename = file.filename or "unknown"

    content = await file.read()
    size_bytes = len(content)

    logger.info(
        "data_route.upload.start",
        tenant_id=tenant_id,
        asset_id=asset_id,
        filename=filename,
        size_bytes=size_bytes,
        chunk_strategy=chunk_strategy,
    )

    try:
        storage.save_bytes(
            tenant_id=tenant_id,
            asset_id=asset_id,
            filename=filename,
            content=content,
        )
    except Exception as exc:
        logger.error(
            "data_route.upload.storage_error",
            asset_id=asset_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist asset: {exc}",
        )

    job_id = dispatcher.dispatch_ingest(
        asset_id=asset_id,
        tenant_id=tenant_id,
        chunk_strategy=chunk_strategy,
    )

    logger.info(
        "data_route.upload.success",
        asset_id=asset_id,
        job_id=job_id,
        tenant_id=tenant_id,
    )

    return UploadResponse(
        asset_id=asset_id,
        job_id=job_id,
        filename=filename,
        size_bytes=size_bytes,
        chunk_strategy=chunk_strategy,
    )


__all__ = ["router"]
