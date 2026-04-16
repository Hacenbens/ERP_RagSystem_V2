"""
AuthMiddleware — JWT RS256 token validation (Sprint 3).

Position in stack: SECOND (after LoggingMiddleware).

Sprint 3 implementation:
    - Validates JWT RS256 signature via JWTHandler
    - Extracts user_id, role, tenant_id from verified claims
    - Injects claims into request.state for downstream RBAC / use-case access
    - Returns 401 with clear error message for all failure cases
"""
from __future__ import annotations

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.infrastructure.auth.jwt_handler import (
    JWTHandler,
    TokenAlgorithmError,
    TokenExpiredError,
    TokenInvalidError,
)
from src.observability.prometheus_metrics import AUTH_FAILURE_RATE, MIDDLEWARE_VIOLATIONS
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# Routes that do NOT require authentication
_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/health",
    "/auth/login",
    "/auth/register",
    "/auth/request-password-reset",
    "/auth/reset-password",
    "/metrics",
})


def _401(reason: str, detail: str) -> JSONResponse:
    AUTH_FAILURE_RATE.labels(reason=reason).inc()
    MIDDLEWARE_VIOLATIONS.labels(middleware="auth").inc()
    return JSONResponse(
        status_code=401,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate JWT RS256 Bearer token on every non-public request.

    Resolves the JWTHandler from app.state.container (set by DI factory at startup).
    Falls back to a fresh JWTHandler if the container is unavailable (tests).
    """

    def _get_jwt_handler(self, request: Request) -> JWTHandler:
        container = getattr(request.app.state, "container", None)
        if container is not None and container.is_bound("jwt_handler"):
            return container.get("jwt_handler")
        return JWTHandler()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header: str | None = request.headers.get("authorization")

        if not auth_header or not auth_header.lower().startswith("bearer "):
            logger.warning("auth.missing_token", path=request.url.path)
            return _401("missing_token", "Authorization header missing or malformed.")

        token = auth_header[len("bearer "):].strip()
        if not token:
            logger.warning("auth.empty_token", path=request.url.path)
            return _401("missing_token", "Bearer token is empty.")

        jwt_handler = self._get_jwt_handler(request)

        try:
            claims = jwt_handler.verify(token)
        except TokenExpiredError:
            logger.warning("auth.token_expired", path=request.url.path)
            return _401("expired_token", "Token has expired.")
        except TokenAlgorithmError as exc:
            logger.warning("auth.wrong_algorithm", path=request.url.path, detail=str(exc))
            return _401("wrong_algorithm", str(exc))
        except TokenInvalidError as exc:
            logger.warning("auth.invalid_token", path=request.url.path, detail=str(exc))
            return _401("invalid_token", f"Invalid token: {exc}")

        # Inject verified claims into request.state for RBAC and use cases
        request.state.user_id = claims.user_id
        request.state.role = claims.role
        request.state.tenant_id = claims.tenant_id

        logger.info(
            "auth.token_verified",
            user_id=claims.user_id,
            role=claims.role,
            path=request.url.path,
        )
        return await call_next(request)


__all__ = ["AuthMiddleware"]
