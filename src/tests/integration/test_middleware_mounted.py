"""
The full five-layer middleware stack, mounted — Sprint 11 (G3·3).

PIIMaskingMiddleware and RateLimitMiddleware were implemented and tested but
never added to the app: main.py mounted three of the five that
src/middleware/__init__.py documents. The LLM endpoint was unthrottled, so one
caller could exhaust the Gemini quota, and no query text was redacted before
reaching a third-party model.

Mounting them alone would have achieved nothing, and these tests pin both
reasons why:

  - _SCAN_PATHS listed /api/erp/query and /query. Neither is the live endpoint
    (/api/v1/query, added in Sprint 7), so the masker never fired.
  - the query route read body.query directly, ignoring the masked text the
    middleware puts on request.state — so even a firing masker changed nothing
    about what reached the model.
"""
from __future__ import annotations


import pytest

from src.middleware.PIIMaskingMiddleware import _SCAN_PATHS
from src.middleware.RateLimitMiddleware import _UNTHROTTLED_PATHS, _USER_LIMIT_PER_MIN
from src.tests.integration.test_app_entrypoint import client  # noqa: F401  (fixture)


class TestAllFiveAreMounted:
    def test_the_stack_matches_the_documented_order(self, client):  # noqa: F811
        """Outermost first: Logging → Auth → RateLimit → RBAC → PIIMasking."""
        names = [m.cls.__name__ for m in client.app.user_middleware]

        assert names == [
            "LoggingMiddleware",
            "AuthMiddleware",
            "RateLimitMiddleware",
            "RBACMiddleware",
            "PIIMaskingMiddleware",
        ]

    def test_rate_limit_sits_inside_auth(self, client):  # noqa: F811
        """It keys on request.state.user_id, which AuthMiddleware sets."""
        names = [m.cls.__name__ for m in client.app.user_middleware]

        assert names.index("AuthMiddleware") < names.index("RateLimitMiddleware")


class TestPiiMaskerCoversTheLiveRoute:
    def test_the_live_query_endpoint_is_scanned(self):
        """The defect: the endpoint the app actually serves was not listed."""
        assert "/api/v1/query" in _SCAN_PATHS

    def test_the_query_route_prefers_the_masked_text(self):
        """Reading body.query directly sent raw PII to the model."""
        import inspect

        from src.routes import query as query_route

        source = inspect.getsource(query_route.query_endpoint)
        assert "masked_query" in source
        assert "route_uc.execute(masked_query" in source

    def test_masking_actually_redacts_an_email(self):
        from src.middleware.PIIMaskingMiddleware import _mask_pii

        masked, counts = _mask_pii("email me at ahmed@example.dz about invoice 7")

        assert "ahmed@example.dz" not in masked
        assert sum(counts.values()) >= 1


class TestOpsProbesAreNotThrottled:
    """Health checks and the metrics scraper must not spend the rate budget."""

    @pytest.mark.parametrize("path", ["/health", "/metrics"])
    def test_probe_paths_are_exempt(self, path):
        assert path in _UNTHROTTLED_PATHS

    def test_health_survives_far_more_requests_than_the_user_limit(self, client):  # noqa: F811
        """Unauthenticated callers share the anonymous bucket.

        A 15-second liveness probe plus a Prometheus scrape would otherwise
        exhaust it on monitoring alone — throttling the health check and hiding
        the metrics that would show it.
        """
        for _ in range(_USER_LIMIT_PER_MIN + 20):
            assert client.get("/health").status_code == 200

    def test_login_is_still_throttled(self):
        """The endpoint worth brute-forcing stays covered."""
        assert "/auth/login" not in _UNTHROTTLED_PATHS


class TestThrottlingIsEnforced:
    """Where the limiter sits determines what it can protect.

    It runs inside AuthMiddleware, so it keys on the authenticated user_id and
    each account gets its own budget. The trade-off: an unauthenticated request
    to a protected path is rejected by Auth first and never reaches the
    limiter. That is deliberate — 401 is cheap, and putting the limiter outside
    Auth would collapse every caller into one shared "anonymous" bucket of 60
    requests a minute. Flood protection ahead of JWT verification belongs at
    the edge proxy, not here.
    """

    def _spam(self, client, n):  # noqa: F811
        return [
            client.post(
                "/auth/login", json={"username": "nobody", "password": "wrongpass1"}
            )
            for _ in range(n)
        ]

    def test_login_is_throttled(self, client):  # noqa: F811
        """Public, so it reaches the limiter — and it is worth brute-forcing."""
        codes = {r.status_code for r in self._spam(client, _USER_LIMIT_PER_MIN + 5)}

        assert 429 in codes, "rate limiting is mounted but never triggers"

    def test_the_429_carries_retry_after(self, client):  # noqa: F811
        throttled = [
            r for r in self._spam(client, _USER_LIMIT_PER_MIN + 5)
            if r.status_code == 429
        ]

        assert throttled
        assert throttled[0].headers.get("Retry-After")

    def test_unauthenticated_protected_paths_are_rejected_before_the_limiter(
        self, client  # noqa: F811
    ):
        """Documents the trade-off above, so the ordering is not changed blind."""
        codes = {
            client.post("/api/v1/query", json={"query": "hi"}).status_code
            for _ in range(_USER_LIMIT_PER_MIN + 5)
        }

        assert codes == {401}
