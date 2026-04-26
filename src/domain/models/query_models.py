"""HTTP request/response contracts for the query pipeline (Sprint 7+)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Body for POST /api/v1/query."""

    query: str = Field(..., min_length=1, max_length=2000)
    erp_module: str | None = Field(default=None)


class QueryResponse(BaseModel):
    """Response envelope for POST /api/v1/query."""

    intent: str
    result: dict[str, Any]
    rag_only: bool
    sql_only: bool


__all__ = ["QueryRequest", "QueryResponse"]
