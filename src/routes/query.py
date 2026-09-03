"""
Query route — Sprint 7 Task 10
POST /api/v1/query — routes a natural-language query through the hybrid agent pipeline.
"""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.agents.hybrid_agent import HybridAgentError
from src.domain.models.hybrid_result import HybridResult
from src.domain.models.query_models import QueryRequest, QueryResponse
from src.domain.models.rag_result import RAGResult
from src.domain.models.sql_result import SQLResult
from src.infrastructure.auth.jwt_handler import TokenClaims
from src.infrastructure.di.factory import build_container
from src.observability.structured_logger import get_logger
from src.use_cases.route_query import BlockedQueryError

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["query"])


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def _get_route_use_case(request: Request):
    """Resolve RouteQueryUseCase from the app's DI container."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        container = build_container()
        request.app.state.container = container
    return container.get("route_query_use_case")


def _get_claims(request: Request) -> TokenClaims:
    """Reconstruct TokenClaims from values injected by AuthMiddleware."""
    return TokenClaims(
        user_id=getattr(request.state, "user_id", ""),
        role=getattr(request.state, "role", ""),
        tenant_id=getattr(request.state, "tenant_id", ""),
        exp=0,
        iat=0,
        sub=getattr(request.state, "user_id", ""),
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Route a natural-language query through the hybrid agent pipeline",
)
async def query_endpoint(
    body: QueryRequest,
    request: Request,
    route_uc=Depends(_get_route_use_case),
) -> QueryResponse:
    """Classify the query and dispatch to RAG, SQL, or Hybrid agent.

    Requires a valid JWT (enforced by AuthMiddleware upstream).
    Returns the agent result plus routing metadata.
    """
    claims = _get_claims(request)

    # PIIMaskingMiddleware puts the redacted text on request.state; it cannot
    # rewrite the request body itself. Reading body.query directly — which this
    # route did — sent the raw text with any email, phone or tax ID straight to
    # a third-party model, with the masking middleware running and doing
    # nothing observable.
    masked_query: str = getattr(request.state, "pii_masked_query", None) or body.query
    pii_hits: dict = getattr(request.state, "pii_hits", {}) or {}

    logger.info(
        "query_route.start",
        tenant_id=claims.tenant_id,
        role=claims.role,
        query_len=len(masked_query),
        pii_entities_masked=sum(pii_hits.values()) if pii_hits else 0,
    )

    try:
        result = await route_uc.execute(masked_query, claims)
    except BlockedQueryError as exc:
        logger.warning("query_route.blocked", reason=str(exc))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except HybridAgentError as exc:
        logger.error("query_route.hybrid_agent_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Both RAG and SQL agents failed — please retry.",
        )

    return _build_response(result)


def _build_response(result: RAGResult | SQLResult | HybridResult) -> QueryResponse:
    """Convert a domain result into the HTTP response shape.

    ``synthetic`` is surfaced at the top level, not buried in ``result``, so a
    caller cannot miss it. Without a configured ERP database the SQL pipeline
    answers from InMemoryExecutor's hardcoded rows — a plain HTTP 200 reading
    "total_amount: 1500000.0" that a business user would take for revenue.
    """
    if isinstance(result, HybridResult):
        return QueryResponse(
            intent="HYBRID",
            result=dataclasses.asdict(result),
            rag_only=result.rag_only,
            sql_only=result.sql_only,
            synthetic=_is_synthetic(result),
        )
    if isinstance(result, RAGResult):
        return QueryResponse(
            intent="RAG",
            result=dataclasses.asdict(result),
            rag_only=False,
            sql_only=False,
            synthetic=False,
        )
    return QueryResponse(
        intent="SQL",
        result=dataclasses.asdict(result),
        rag_only=False,
        sql_only=False,
        synthetic=result.synthetic,
    )


def _is_synthetic(result: HybridResult) -> bool:
    """A hybrid answer is synthetic if its SQL half was.

    Merged prose quotes the SQL figures, so a synthetic SQL branch taints the
    whole answer even when the RAG half is genuine.
    """
    sql_part = getattr(result, "sql_result", None)
    return bool(getattr(sql_part, "synthetic", False))


__all__ = ["router"]
