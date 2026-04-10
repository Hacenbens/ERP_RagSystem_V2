"""
RateLimitMiddleware — per-user and per-IP request throttling.

Position in stack: THIRD (after AuthMiddleware).

Enforced limits:
    60  requests / minute  per authenticated user_id  → 429
    200 requests / minute  per client IP              → 429

Uses a simple sliding-window counter (in-process, resets on restart).
Distributed enforcement (Redis) is a Sprint 6+ concern.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.observability.prometheus_metrics import MIDDLEWARE_VIOLATIONS
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# Sprint 5 target limits (enforced in full implementation)
_USER_LIMIT_PER_MIN: int = 60
_IP_LIMIT_PER_MIN: int = 200
_WINDOW_SECONDS: int = 60


class _WindowCounter:
    """Minimal sliding-window counter (in-process, not distributed)."""

    def __init__(self) -> None:
        self._counts: dict[str, list[float]] = defaultdict(list)

    def increment(self, key: str) -> int:
        """Record a hit for *key* and return the count within the window."""
        now = time.monotonic()
        window_start = now - _WINDOW_SECONDS
        hits = self._counts[key]
        # Evict timestamps outside the window
        self._counts[key] = [t for t in hits if t >= window_start]
        self._counts[key].append(now)
        return len(self._counts[key])


_user_counter = _WindowCounter()
_ip_counter = _WindowCounter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Throttle requests by user_id and client IP.

    Returns 429 with a Retry-After header when a limit is exceeded.
    User limit is checked first; IP limit second.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Check rate counters; return 429 when a limit is exceeded."""
        user_id: str = getattr(request.state, "user_id", "") or (
            request.headers.get("x-user-id", "anonymous")
        )
        client_ip: str = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )

        user_count = _user_counter.increment(user_id)
        if user_count > _USER_LIMIT_PER_MIN:
            MIDDLEWARE_VIOLATIONS.labels(middleware="rate_limit_user").inc()
            logger.warning(
                "rate_limit.user_exceeded",
                user_id=user_id,
                count=user_count,
                limit=_USER_LIMIT_PER_MIN,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded (user)."},
                headers={"Retry-After": str(_WINDOW_SECONDS)},
            )

        ip_count = _ip_counter.increment(client_ip)
        if ip_count > _IP_LIMIT_PER_MIN:
            MIDDLEWARE_VIOLATIONS.labels(middleware="rate_limit_ip").inc()
            logger.warning(
                "rate_limit.ip_exceeded",
                client_ip=client_ip,
                count=ip_count,
                limit=_IP_LIMIT_PER_MIN,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded (IP)."},
                headers={"Retry-After": str(_WINDOW_SECONDS)},
            )

        return await call_next(request)


__all__ = ["RateLimitMiddleware"]
