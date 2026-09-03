"""HTTP request/response contracts for the asset upload pipeline (Sprint 7+)."""
from __future__ import annotations

from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Response for POST /api/assets/upload — HTTP 202."""

    asset_id: str
    job_id: str
    filename: str
    size_bytes: int
    chunk_strategy: str


__all__ = ["UploadResponse"]
