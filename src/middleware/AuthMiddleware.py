"""
AuthMiddleware — JWT RS256 token validation (Sprint 1 stub).

Position in stack: SECOND (after LoggingMiddleware).

Full implementation in Sprint 3:
    - Validates JWT RS256 signature via jwt_handler.py
    - Extracts user_id, role, tenant_id from claims
    - Writes user_id into X-User-ID header for LoggingMiddleware (on replay)
      and into request.state for downstream RBAC / use-case access

Sprint 1 stub behaviour:
    - Checks for Authorization header presence
    - If missing → increments AUTH_FAILURE_RATE, returns 401
    - If present → passes through (no real signature verification yet)
    - Sets request.state.user_id and request.state.role to stub values
"""
from __future__ import annotations

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.observability.prometheus_metrics import AUTH_FAILURE_RATE
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# Routes that do NOT require authentication
_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/health",
    "/auth/login",
    "/auth/register",
    "/metrics",
})


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate JWT Bearer token on every non-public request.

    Sprint 1: stub — presence check only, no signature verification.
    Sprint 3: full RS256 verification, claim extraction, UserContext injection.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Check Authorization header; block with 401 if absent on protected routes."""
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header: str | None = request.headers.get("authorization")
        token = auth_header[len("bearer "):].strip() if auth_header else ""

        if not auth_header or not auth_header.lower().startswith("bearer ") or not token:
            AUTH_FAILURE_RATE.labels(reason="missing_token").inc()
            logger.warning(
                "auth.missing_token",
                path=request.url.path,
                method=request.method,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization header missing or malformed."},
            )

        # Sprint 1 stub: accept any non-empty token, inject placeholder state
        # Sprint 3 will replace this block with real RS256 verification
        request.state.user_id = "stub-user"
        request.state.role = "ADMIN"          # permissive during Sprint 1
        request.state.tenant_id = "stub-tenant"

        logger.info(
            "auth.token_accepted",
            path=request.url.path,
            stub=True,
        )
        return await call_next(request)


__all__ = ["AuthMiddleware"]
