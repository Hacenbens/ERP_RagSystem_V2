"""
Performance tests — full middleware stack latency (Sprint 5, Task 5).

Acceptance criteria:
  - p99 latency through the full 5-layer authenticated stack < 20ms
  - p95 latency on the authenticated path < 15ms
  - p95 latency on the public health path (Logging + RateLimit only) < 10ms
  - PIIMaskingMiddleware (POST + JSON body) adds < 5ms overhead vs GET baseline

Stack under test (request order):
  LoggingMiddleware → AuthMiddleware → RateLimitMiddleware → RBACMiddleware
  → PIIMaskingMiddleware → route handler

Measurement methodology:
  - Starlette TestClient (synchronous in-process transport)
  - 5-request warm-up to eliminate JIT / import cold-start skew
  - N = 50 timed requests per scenario
  - N ≪ 60/min rate-limit per user — safe during a single test run
  - time.perf_counter() wraps each client call for sub-millisecond resolution
  - Timings collected as a sorted list; percentiles computed by index

Naming: test_{stack}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

from collections.abc import Iterator

import json
import sys
import time
from pathlib import Path
from typing import Callable

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.auth.jwt_handler import JWTHandler
from src.infrastructure.auth.user_repository import InMemoryUserRepository
from src.infrastructure.di.container import DIContainer
from src.middleware.AuthMiddleware import AuthMiddleware
from src.middleware.LoggingMiddleware import LoggingMiddleware
from src.middleware.PIIMaskingMiddleware import PIIMaskingMiddleware
from src.middleware.RateLimitMiddleware import RateLimitMiddleware
from src.middleware.RBACMiddleware import RBACMiddleware
from src.tests.fixtures.jwt_fixtures import make_jwt_handler, make_valid_token
from src.use_cases.auth_user import AuthUseCase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WARMUP_REQUESTS: int = 5
_SAMPLE_SIZE: int = 50

# Latency budgets (milliseconds)
_P95_PUBLIC_MS: float = 10.0
_P95_AUTH_MS: float = 15.0
_P99_AUTH_MS: float = 20.0
_PII_OVERHEAD_MS: float = 5.0


# ---------------------------------------------------------------------------
# App factory — full 5-layer stack
# ---------------------------------------------------------------------------

def _build_full_stack_app(jwt_handler: JWTHandler) -> FastAPI:
    """Build a FastAPI app with all 5 middleware layers.

    add_middleware is LIFO — last added = outermost = first to process request:
      app.add_middleware(PIIMaskingMiddleware)   → innermost
      app.add_middleware(RBACMiddleware)
      app.add_middleware(RateLimitMiddleware)
      app.add_middleware(AuthMiddleware)
      app.add_middleware(LoggingMiddleware)      → outermost
    """
    user_repo = InMemoryUserRepository()
    auth_use_case = AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler)

    container = DIContainer()
    container.register("jwt_handler", jwt_handler)
    container.register("user_repository", user_repo)
    container.register("auth_use_case", auth_use_case)
    container.validate()

    app = FastAPI()
    app.state.container = container

    # Innermost first (LIFO)
    app.add_middleware(PIIMaskingMiddleware)
    app.add_middleware(RBACMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/erp/query")
    async def erp_query_get(request: Request):
        return {"result": "ok", "role": getattr(request.state, "role", None)}

    @app.post("/api/erp/query")
    async def erp_query_post(request: Request):
        masked = getattr(request.state, "pii_masked_query", None)
        return {"result": "ok", "masked_query": masked}

    @app.get("/admin/status")
    async def admin_status():
        return {"status": "healthy"}

    return app


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list[float], p: float) -> float:
    """Return the p-th percentile from a pre-sorted list (0 < p ≤ 100)."""
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * p / 100) - 1
    return sorted_values[max(0, idx)]


def _measure(
    call: Callable[[], object],
    n: int = _SAMPLE_SIZE,
    warmup: int = _WARMUP_REQUESTS,
) -> dict[str, float]:
    """Run *call* n+warmup times and return p50/p95/p99 in milliseconds."""
    for _ in range(warmup):
        call()

    timings: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        call()
        timings.append((time.perf_counter() - t0) * 1000)

    timings.sort()
    return {
        "p50": _percentile(timings, 50),
        "p95": _percentile(timings, 95),
        "p99": _percentile(timings, 99),
        "min": timings[0],
        "max": timings[-1],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def jwt_handler() -> JWTHandler:
    return make_jwt_handler()


@pytest.fixture(scope="module")
def full_stack_client(jwt_handler) -> Iterator[TestClient]:
    app = _build_full_stack_app(jwt_handler)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _auth_header(jwt_handler: JWTHandler, role: str = "SUPER_ADMIN", user_id: str = "perf-user") -> dict:
    """Return an Authorization header. Each (role, user_id) pair lands in its
    own rate-limit bucket — pass a unique user_id per test scenario to prevent
    cross-test rate-limit accumulation across the module-scoped client."""
    token = make_valid_token(jwt_handler, user_id=user_id, role=role, tenant_id="perf-tenant")
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Scenario 1 — Public health endpoint (Logging + RateLimit pass-through only)
# ===========================================================================

class TestPublicPathLatency:
    """Health endpoint traverses LoggingMiddleware + RateLimitMiddleware only.

    Auth/RBAC/PII are bypassed — isolates base overhead of two lightweight layers.
    X-User-ID header pins requests to a unique rate-limit bucket per scenario.
    """

    _HEADERS = {"X-User-ID": "perf-health-user"}

    def test_health_p95_within_budget(self, full_stack_client):
        stats = _measure(lambda: full_stack_client.get("/health", headers=self._HEADERS))
        assert stats["p95"] < _P95_PUBLIC_MS, (
            f"Health p95={stats['p95']:.2f}ms exceeds budget of {_P95_PUBLIC_MS}ms "
            f"(p50={stats['p50']:.2f}ms, p99={stats['p99']:.2f}ms)"
        )


# ===========================================================================
# Scenario 2 — Authenticated GET (full stack, no PII scan)
# ===========================================================================

class TestAuthenticatedGetLatency:
    """GET /api/erp/query traverses all 5 layers but PIIMaskingMiddleware
    performs no body scan (GET requests have no JSON body).

    Unique user_id per scenario keeps this class within its own rate-limit bucket.
    """

    _USER_ID = "perf-auth-get-user"

    def test_authenticated_get_p95_within_budget(self, full_stack_client, jwt_handler):
        headers = _auth_header(jwt_handler, user_id=self._USER_ID)
        stats = _measure(lambda: full_stack_client.get("/api/erp/query", headers=headers))
        assert stats["p95"] < _P95_AUTH_MS, (
            f"Authenticated GET p95={stats['p95']:.2f}ms exceeds budget of {_P95_AUTH_MS}ms "
            f"(p50={stats['p50']:.2f}ms, p99={stats['p99']:.2f}ms)"
        )

    def test_authenticated_get_p99_within_budget(self, full_stack_client, jwt_handler):
        headers = _auth_header(jwt_handler, user_id=f"{self._USER_ID}-p99")
        stats = _measure(lambda: full_stack_client.get("/api/erp/query", headers=headers))
        assert stats["p99"] < _P99_AUTH_MS, (
            f"Authenticated GET p99={stats['p99']:.2f}ms exceeds budget of {_P99_AUTH_MS}ms "
            f"(p50={stats['p50']:.2f}ms, p95={stats['p95']:.2f}ms)"
        )


# ===========================================================================
# Scenario 3 — Authenticated POST with PII body (full stack + PII scan)
# ===========================================================================

class TestAuthenticatedPostWithPIILatency:
    """POST /api/erp/query with a JSON body triggers PIIMaskingMiddleware scan.

    Measures full 5-layer overhead including regex evaluation on body text.
    """

    _CLEAN_BODY = json.dumps({"query": "Show inventory levels for warehouse Blida region Q3"})
    _PII_BODY = json.dumps({
        "query": (
            "Send invoice to ahmed.benali@ferza-corp.dz, "
            "NIF 123456789012345, phone 0661234567"
        )
    })

    def test_post_clean_body_p99_within_budget(self, full_stack_client, jwt_handler):
        headers = {
            **_auth_header(jwt_handler, user_id="perf-post-clean-user"),
            "content-type": "application/json",
        }
        stats = _measure(
            lambda: full_stack_client.post(
                "/api/erp/query", content=self._CLEAN_BODY, headers=headers
            )
        )
        assert stats["p99"] < _P99_AUTH_MS, (
            f"POST clean body p99={stats['p99']:.2f}ms exceeds {_P99_AUTH_MS}ms budget"
        )

    def test_post_pii_body_p99_within_budget(self, full_stack_client, jwt_handler):
        """PII scan (email + phone + tax_id regex) must not push p99 over budget."""
        headers = {
            **_auth_header(jwt_handler, user_id="perf-post-pii-user"),
            "content-type": "application/json",
        }
        stats = _measure(
            lambda: full_stack_client.post(
                "/api/erp/query", content=self._PII_BODY, headers=headers
            )
        )
        assert stats["p99"] < _P99_AUTH_MS, (
            f"POST PII body p99={stats['p99']:.2f}ms exceeds {_P99_AUTH_MS}ms budget"
        )

    def test_pii_scan_overhead_vs_get_baseline(self, full_stack_client, jwt_handler):
        """PII body scan overhead (POST vs GET delta) must be < 5ms at p95."""
        get_headers = _auth_header(jwt_handler, user_id="perf-overhead-get-user")
        post_headers = {
            **_auth_header(jwt_handler, user_id="perf-overhead-post-user"),
            "content-type": "application/json",
        }

        get_stats = _measure(
            lambda: full_stack_client.get("/api/erp/query", headers=get_headers)
        )
        post_stats = _measure(
            lambda: full_stack_client.post(
                "/api/erp/query", content=self._PII_BODY, headers=post_headers
            )
        )
        overhead = post_stats["p95"] - get_stats["p95"]
        assert overhead < _PII_OVERHEAD_MS, (
            f"PII scan overhead at p95 is {overhead:.2f}ms — exceeds {_PII_OVERHEAD_MS}ms budget "
            f"(GET p95={get_stats['p95']:.2f}ms, POST p95={post_stats['p95']:.2f}ms)"
        )


# ===========================================================================
# Scenario 4 — 403 short-circuit (RBAC blocks before route handler runs)
# ===========================================================================

class TestBlockedRequestLatency:
    """Blocked requests (403) should be faster than allowed ones —
    RBAC short-circuits before the route handler executes.

    Uses a unique user_id to avoid sharing the rate-limit bucket with other scenarios.
    """

    _USER_ID = "perf-blocked-user"

    def test_blocked_request_p99_below_auth_budget(self, full_stack_client, jwt_handler):
        """REPORTING_ANALYST blocked by RBACMiddleware — must be ≤ auth budget."""
        headers = _auth_header(jwt_handler, role="REPORTING_ANALYST", user_id=self._USER_ID)
        stats = _measure(lambda: full_stack_client.get("/api/erp/query", headers=headers))
        assert stats["p99"] < _P99_AUTH_MS, (
            f"Blocked request p99={stats['p99']:.2f}ms — should be fast (short-circuit)"
        )


# ===========================================================================
# Scenario 5 — Stack does not degrade under sequential load (no regression)
# ===========================================================================

class TestLatencyStability:
    """Latency must not drift upward across 50 sequential requests —
    sliding-window eviction in RateLimitMiddleware must stay O(n) bounded.
    """

    def test_latency_does_not_degrade_across_samples(self, full_stack_client, jwt_handler):
        """First-half p95 and second-half p95 must differ by < 5ms."""
        headers = _auth_header(jwt_handler, user_id="perf-stability-user")

        timings: list[float] = []
        for _ in range(_WARMUP_REQUESTS):
            full_stack_client.get("/api/erp/query", headers=headers)

        for _ in range(_SAMPLE_SIZE):
            t0 = time.perf_counter()
            full_stack_client.get("/api/erp/query", headers=headers)
            timings.append((time.perf_counter() - t0) * 1000)

        first_half = sorted(timings[: _SAMPLE_SIZE // 2])
        second_half = sorted(timings[_SAMPLE_SIZE // 2 :])

        p95_first = _percentile(first_half, 95)
        p95_second = _percentile(second_half, 95)
        drift = abs(p95_second - p95_first)

        assert drift < 5.0, (
            f"Latency drifted {drift:.2f}ms between first and second half "
            f"(first p95={p95_first:.2f}ms, second p95={p95_second:.2f}ms)"
        )
