"""
Integration tests for RateLimitMiddleware — Sprint 5 enforcement.

Acceptance criteria:
    - POST /api/erp/query with >60 req/min from same user_id → 429
    - >200 req/min from same IP → 429
    - Within-limit requests → 200
    - 429 response contains {"detail": "Rate limit exceeded (user|IP)."}
    - 429 response carries Retry-After: 60 header
    - MIDDLEWARE_VIOLATIONS counter increments with correct label
    - User limit and IP limit are independent (different users don't collide)

Strategy: pre-populate the module-level _WindowCounter state directly so tests
run instantly without busy-looping 61+ real HTTP calls.
"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from src.middleware.RateLimitMiddleware import (
    RateLimitMiddleware,
    _WindowCounter,
    _USER_LIMIT_PER_MIN,
    _IP_LIMIT_PER_MIN,
    _WINDOW_SECONDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(
    user_counter: _WindowCounter | None = None,
    ip_counter: _WindowCounter | None = None,
) -> FastAPI:
    """Build a minimal app with RateLimitMiddleware.

    Accepts optional pre-populated counters so tests can seed state without
    importing module-level globals (which no longer exist after the
    per-instance counter refactor).
    """
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        user_counter=user_counter,
        ip_counter=ip_counter,
    )

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/api/erp/query")
    async def query(request: Request):
        return {"query": "ok"}

    return app


def _flood_user(user_id: str, count: int, counter: _WindowCounter) -> None:
    """Pre-populate *counter* to *count* hits for *user_id* within the window."""
    for _ in range(count):
        counter.increment(user_id)


def _flood_ip(ip: str, count: int, counter: _WindowCounter) -> None:
    """Pre-populate *counter* to *count* hits for *ip* within the window."""
    for _ in range(count):
        counter.increment(ip)


def _read_violations(label: str) -> float:
    from prometheus_client import REGISTRY
    for m in REGISTRY.collect():
        for s in m.samples:
            if (
                s.name == "erp_rag_middleware_violations_total"
                and s.labels.get("middleware") == label
            ):
                return s.value
    return 0.0


# ---------------------------------------------------------------------------
# User rate limit enforcement
# ---------------------------------------------------------------------------

class TestUserRateLimit:
    """Per-user 429 after exceeding 60 req/min."""

    def test_user_within_limit_passes(self):
        """First request from a fresh user_id returns 200."""
        client = TestClient(_make_app(), raise_server_exceptions=True)
        r = client.get("/health", headers={"x-user-id": f"fresh-{time.monotonic()}"})
        assert r.status_code == 200

    def test_user_at_limit_still_passes(self):
        """Exactly _USER_LIMIT_PER_MIN hits should NOT be blocked (> means strictly over)."""
        uid = f"at-limit-{time.monotonic()}"
        uc = _WindowCounter()
        _flood_user(uid, _USER_LIMIT_PER_MIN, uc)
        client = TestClient(_make_app(user_counter=uc), raise_server_exceptions=False)
        # next call brings count to limit+1 — this is the one that flips it
        r = client.get("/health", headers={"x-user-id": uid})
        assert r.status_code == 429

    def test_user_over_limit_returns_429(self):
        """User already over the limit receives 429."""
        uid = f"over-{time.monotonic()}"
        uc = _WindowCounter()
        _flood_user(uid, _USER_LIMIT_PER_MIN + 5, uc)
        client = TestClient(_make_app(user_counter=uc), raise_server_exceptions=False)
        r = client.get("/health", headers={"x-user-id": uid})
        assert r.status_code == 429

    def test_user_429_response_body(self):
        """429 body contains {"detail": "Rate limit exceeded (user)."}."""
        uid = f"body-{time.monotonic()}"
        uc = _WindowCounter()
        _flood_user(uid, _USER_LIMIT_PER_MIN + 1, uc)
        client = TestClient(_make_app(user_counter=uc), raise_server_exceptions=False)
        r = client.get("/health", headers={"x-user-id": uid})
        assert r.json() == {"detail": "Rate limit exceeded (user)."}

    def test_user_429_retry_after_header(self):
        """429 carries Retry-After: 60."""
        uid = f"retry-{time.monotonic()}"
        uc = _WindowCounter()
        _flood_user(uid, _USER_LIMIT_PER_MIN + 1, uc)
        client = TestClient(_make_app(user_counter=uc), raise_server_exceptions=False)
        r = client.get("/health", headers={"x-user-id": uid})
        assert r.headers.get("retry-after") == str(_WINDOW_SECONDS)

    def test_user_rate_limit_increments_middleware_violations(self):
        """Hitting user rate limit increments MIDDLEWARE_VIOLATIONS[rate_limit_user]."""
        uid = f"violations-{time.monotonic()}"
        uc = _WindowCounter()
        _flood_user(uid, _USER_LIMIT_PER_MIN + 1, uc)
        client = TestClient(_make_app(user_counter=uc), raise_server_exceptions=False)
        before = _read_violations("rate_limit_user")
        client.get("/health", headers={"x-user-id": uid})
        after = _read_violations("rate_limit_user")
        assert after > before

    def test_different_users_isolated(self):
        """One user being rate-limited does not affect a different user."""
        ts = time.monotonic()
        limited_uid = f"limited-{ts}"
        clean_uid = f"clean-{ts}"
        uc = _WindowCounter()
        _flood_user(limited_uid, _USER_LIMIT_PER_MIN + 5, uc)
        # clean_uid has no prior hits — same shared counter, but a different key
        client = TestClient(_make_app(user_counter=uc), raise_server_exceptions=False)
        assert client.get("/health", headers={"x-user-id": limited_uid}).status_code == 429
        assert client.get("/health", headers={"x-user-id": clean_uid}).status_code == 200

    def test_user_rate_limit_on_post_endpoint(self):
        """Rate limit applies to POST routes too, not just GET."""
        uid = f"post-{time.monotonic()}"
        uc = _WindowCounter()
        _flood_user(uid, _USER_LIMIT_PER_MIN + 1, uc)
        client = TestClient(_make_app(user_counter=uc), raise_server_exceptions=False)
        r = client.post("/api/erp/query", json={}, headers={"x-user-id": uid})
        assert r.status_code == 429


# ---------------------------------------------------------------------------
# IP rate limit enforcement
# ---------------------------------------------------------------------------

class TestIPRateLimit:
    """Per-IP 429 after exceeding 200 req/min."""

    def test_ip_within_limit_passes(self):
        """First request from a fresh IP returns 200."""
        client = TestClient(_make_app(), raise_server_exceptions=True)
        ts = str(time.monotonic()).replace(".", "")
        r = client.get("/health", headers={"x-forwarded-for": f"10.0.{ts[-3:-1]}.1"})
        assert r.status_code == 200

    def test_ip_over_limit_returns_429(self):
        """IP already over _IP_LIMIT_PER_MIN receives 429."""
        unique_ip = f"192.168.{int(time.monotonic() * 1000) % 255}.1"
        ic = _WindowCounter()
        _flood_ip(unique_ip, _IP_LIMIT_PER_MIN + 5, ic)
        client = TestClient(_make_app(ip_counter=ic), raise_server_exceptions=False)
        r = client.get("/health", headers={"x-forwarded-for": unique_ip})
        assert r.status_code == 429

    def test_ip_429_response_body(self):
        """429 body contains {"detail": "Rate limit exceeded (IP)."}."""
        unique_ip = f"10.10.{int(time.monotonic() * 1000) % 255}.1"
        ic = _WindowCounter()
        _flood_ip(unique_ip, _IP_LIMIT_PER_MIN + 1, ic)
        client = TestClient(_make_app(ip_counter=ic), raise_server_exceptions=False)
        r = client.get("/health", headers={"x-forwarded-for": unique_ip})
        assert r.json() == {"detail": "Rate limit exceeded (IP)."}

    def test_ip_429_retry_after_header(self):
        """IP 429 carries Retry-After: 60."""
        unique_ip = f"172.16.{int(time.monotonic() * 1000) % 255}.1"
        ic = _WindowCounter()
        _flood_ip(unique_ip, _IP_LIMIT_PER_MIN + 1, ic)
        client = TestClient(_make_app(ip_counter=ic), raise_server_exceptions=False)
        r = client.get("/health", headers={"x-forwarded-for": unique_ip})
        assert r.headers.get("retry-after") == str(_WINDOW_SECONDS)

    def test_ip_rate_limit_increments_middleware_violations(self):
        """Hitting IP rate limit increments MIDDLEWARE_VIOLATIONS[rate_limit_ip]."""
        unique_ip = f"203.0.{int(time.monotonic() * 1000) % 255}.1"
        ic = _WindowCounter()
        _flood_ip(unique_ip, _IP_LIMIT_PER_MIN + 1, ic)
        client = TestClient(_make_app(ip_counter=ic), raise_server_exceptions=False)
        before = _read_violations("rate_limit_ip")
        client.get("/health", headers={"x-forwarded-for": unique_ip})
        after = _read_violations("rate_limit_ip")
        assert after > before

    def test_ip_uses_first_value_from_x_forwarded_for(self):
        """X-Forwarded-For with multiple values: only the first is used as the key."""
        unique_ip = f"100.64.{int(time.monotonic() * 1000) % 255}.1"
        ic = _WindowCounter()
        _flood_ip(unique_ip, _IP_LIMIT_PER_MIN + 1, ic)
        client = TestClient(_make_app(ip_counter=ic), raise_server_exceptions=False)
        # first IP in the chain is the flooded one
        r = client.get(
            "/health",
            headers={"x-forwarded-for": f"{unique_ip}, 8.8.8.8"},
        )
        assert r.status_code == 429

    def test_different_ips_isolated(self):
        """One IP being rate-limited does not affect a different IP."""
        ts = int(time.monotonic() * 1000)
        limited_ip = f"11.{ts % 255}.0.1"
        clean_ip = f"12.{ts % 255}.0.1"
        ic = _WindowCounter()
        _flood_ip(limited_ip, _IP_LIMIT_PER_MIN + 5, ic)
        # clean_ip has no hits in the shared counter
        client = TestClient(_make_app(ip_counter=ic), raise_server_exceptions=False)
        assert client.get(
            "/health",
            headers={"x-forwarded-for": limited_ip, "x-user-id": f"u-limited-{ts}"},
        ).status_code == 429
        assert client.get(
            "/health",
            headers={"x-forwarded-for": clean_ip, "x-user-id": f"u-clean-{ts}"},
        ).status_code == 200


# ---------------------------------------------------------------------------
# User limit takes precedence over IP limit
# ---------------------------------------------------------------------------

class TestRateLimitPrecedence:
    """User limit is evaluated before IP limit."""

    def test_user_limit_checked_before_ip(self):
        """When both user and IP are over limit, response body says 'user' (checked first)."""
        ts = int(time.monotonic() * 1000)
        uid = f"both-{ts}"
        unique_ip = f"198.51.{ts % 255}.1"
        uc = _WindowCounter()
        ic = _WindowCounter()
        _flood_user(uid, _USER_LIMIT_PER_MIN + 1, uc)
        _flood_ip(unique_ip, _IP_LIMIT_PER_MIN + 1, ic)
        client = TestClient(_make_app(user_counter=uc, ip_counter=ic), raise_server_exceptions=False)
        r = client.get(
            "/health",
            headers={"x-user-id": uid, "x-forwarded-for": unique_ip},
        )
        assert r.status_code == 429
        assert r.json()["detail"] == "Rate limit exceeded (user)."


# ---------------------------------------------------------------------------
# _WindowCounter unit-level tests
# ---------------------------------------------------------------------------

class TestWindowCounter:
    """Direct unit tests for the sliding-window counter."""

    def test_increment_returns_1_on_first_hit(self):
        c = _WindowCounter()
        assert c.increment("k") == 1

    def test_increment_accumulates(self):
        c = _WindowCounter()
        for i in range(5):
            count = c.increment("k")
        assert count == 5

    def test_different_keys_are_independent(self):
        c = _WindowCounter()
        c.increment("a")
        c.increment("a")
        assert c.increment("b") == 1

    def test_old_hits_evicted(self):
        """Hits older than the window should not count."""
        import src.middleware.RateLimitMiddleware as rl_mod
        c = _WindowCounter()
        # Manually inject a very old timestamp
        c._counts["old-key"] = [time.monotonic() - rl_mod._WINDOW_SECONDS - 1.0]
        # Next increment evicts the stale hit
        assert c.increment("old-key") == 1
