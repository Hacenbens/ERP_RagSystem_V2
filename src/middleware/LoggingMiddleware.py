"""
LoggingMiddleware — outermost layer of the middleware stack.

Responsibilities:
1. Generate a unique trace_id per request (UUID4) or propagate one from
   the X-Request-ID header if the upstream gateway supplies it.
2. Extract user_id from the X-User-ID header (populated by AuthMiddleware
   on the inbound path; empty string on unauthenticated requests).
3. Bind trace_id and user_id into the async context via set_trace_context()
   so every downstream log line carries them automatically.
4. After the response is produced, emit one JSON log line with:
       trace_id, user_id, method, path, status_code, latency_ms
5. Increment REQUEST_LATENCY histogram and REQUEST_COUNT counter.

Position in stack: FIRST (wraps all other middleware and route handlers).
"""
from __future__ import annotations

import time
import uuid
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.observability.prometheus_metrics import REQUEST_COUNT, REQUEST_LATENCY
from src.observability.structured_logger import get_logger, set_trace_context

logger = get_logger(__name__)

# Header names
_HEADER_REQUEST_ID = "x-request-id"
_HEADER_USER_ID = "x-user-id"


class LoggingMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that logs every request as a JSON line.

    Attach to a FastAPI app::

        from src.middleware.LoggingMiddleware import LoggingMiddleware
        app.add_middleware(LoggingMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process the request: set context, call handler, log result."""
        # ----------------------------------------------------------------
        # 1. Resolve trace_id — prefer upstream header, else generate one
        # ----------------------------------------------------------------
        trace_id: str = (
            request.headers.get(_HEADER_REQUEST_ID) or str(uuid.uuid4())
        )

        # ----------------------------------------------------------------
        # 2. Extract user_id (set by AuthMiddleware on inbound path)
        # ----------------------------------------------------------------
        user_id: str = request.headers.get(_HEADER_USER_ID, "")

        # ----------------------------------------------------------------
        # 3. Bind into async context — propagates to all downstream loggers
        # ----------------------------------------------------------------
        set_trace_context(trace_id=trace_id, user_id=user_id)

        # ----------------------------------------------------------------
        # 4. Call downstream middleware / route handler
        # ----------------------------------------------------------------
        start = time.perf_counter()
        status_code = 500  # default — overwritten on success

        try:
            response: Response = await call_next(request)
            status_code = response.status_code
        except Exception:
            logger.error(
                "request.unhandled_exception",
                method=request.method,
                path=request.url.path,
            )
            raise
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            endpoint = request.url.path
            method = request.method
            status_str = str(status_code)

            # ----------------------------------------------------------------
            # 5. Emit structured log line
            # ----------------------------------------------------------------
            logger.info(
                "request.completed",
                method=method,
                path=endpoint,
                status_code=status_code,
                latency_ms=latency_ms,
            )

            # ----------------------------------------------------------------
            # 6. Prometheus metrics
            # ----------------------------------------------------------------
            REQUEST_LATENCY.labels(
                method=method,
                endpoint=endpoint,
                status_code=status_str,
            ).observe(latency_ms / 1000)

            REQUEST_COUNT.labels(
                method=method,
                endpoint=endpoint,
                status_code=status_str,
            ).inc()

        # Propagate trace_id to the client for correlation
        response.headers["x-request-id"] = trace_id
        return response


__all__ = ["LoggingMiddleware"]
