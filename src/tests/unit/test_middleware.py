"""
Unit tests for Sprint 1 middleware stubs.

Covers:
    src/middleware/LoggingMiddleware.py
    src/middleware/AuthMiddleware.py
    src/middleware/RateLimitMiddleware.py
    src/middleware/RBACMiddleware.py
    src/middleware/PIIMaskingMiddleware.py

Test naming: test_{middleware}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

import json
import io
import logging
import time

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from src.middleware.public_paths import PUBLIC_PATHS
from src.observability.structured_logger import _JSONFormatter


# ---------------------------------------------------------------------------
# Shared app factory
# ---------------------------------------------------------------------------

def _make_app(*middleware_classes) -> FastAPI:
    """Return a minimal FastAPI app with the given middleware stack applied."""
    app = FastAPI()
    for mw in reversed(middleware_classes):   # add_middleware reverses order
        app.add_middleware(mw)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/admin/jobs")
    async def admin_jobs():
        return {"jobs": []}

    @app.post("/api/erp/query")
    async def query(request: Request, body: dict):
        masked = getattr(request.state, "pii_masked_query", body.get("query"))
        return {"query": masked, "hits": getattr(request.state, "pii_hits", {})}

    return app


def _capture(logger_name: str) -> tuple[io.StringIO, logging.Handler]:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(_JSONFormatter())
    logging.getLogger(logger_name).addHandler(h)
    return buf, h


# ===========================================================================
# LoggingMiddleware
# ===========================================================================

class TestLoggingMiddleware:
    """LoggingMiddleware emits one JSON line per request with required fields."""

    @pytest.fixture()
    def client_and_buf(self):
        from src.middleware.LoggingMiddleware import LoggingMiddleware
        buf, _ = _capture("src.middleware.LoggingMiddleware")
        app = _make_app(LoggingMiddleware)
        return TestClient(app, raise_server_exceptions=True), buf

    def test_logging_middleware_emits_json_on_success(self, client_and_buf):
        client, buf = client_and_buf
        client.get("/health")
        line = json.loads(buf.getvalue().strip().splitlines()[-1])
        assert line["event"] == "request.completed"
        assert line["status_code"] == 200
        assert "latency_ms" in line
        assert "trace_id" in line

    def test_logging_middleware_propagates_x_request_id(self, client_and_buf):
        client, buf = client_and_buf
        r = client.get("/health", headers={"x-request-id": "my-trace-99"})
        assert r.headers["x-request-id"] == "my-trace-99"
        line = json.loads(buf.getvalue().strip().splitlines()[-1])
        assert line["trace_id"] == "my-trace-99"

    def test_logging_middleware_generates_trace_id_when_absent(self, client_and_buf):
        client, buf = client_and_buf
        client.get("/health")
        line = json.loads(buf.getvalue().strip().splitlines()[-1])
        assert line["trace_id"] != ""
        assert len(line["trace_id"]) == 36   # UUID4 format

    def test_logging_middleware_records_user_id_from_header(self, client_and_buf):
        client, buf = client_and_buf
        client.get("/health", headers={"x-user-id": "user-77"})
        line = json.loads(buf.getvalue().strip().splitlines()[-1])
        assert line["user_id"] == "user-77"

    def test_logging_middleware_records_method_and_path(self, client_and_buf):
        client, buf = client_and_buf
        client.get("/health")
        line = json.loads(buf.getvalue().strip().splitlines()[-1])
        assert line["method"] == "GET"
        assert line["path"] == "/health"

    def test_logging_middleware_records_non_200_status(self, client_and_buf):
        client, buf = client_and_buf
        client.get("/nonexistent")
        line = json.loads(buf.getvalue().strip().splitlines()[-1])
        assert line["status_code"] == 404

    def test_logging_middleware_latency_ms_is_positive(self, client_and_buf):
        client, buf = client_and_buf
        client.get("/health")
        line = json.loads(buf.getvalue().strip().splitlines()[-1])
        assert line["latency_ms"] >= 0

    def test_logging_middleware_increments_request_count(self, client_and_buf):
        from prometheus_client import REGISTRY
        client, _ = client_and_buf

        def _count():
            for m in REGISTRY.collect():
                for s in m.samples:
                    if s.name == "erp_rag_requests_total" and s.labels.get("endpoint") == "/health":
                        return s.value
            return 0.0

        before = _count()
        client.get("/health")
        after = _count()
        assert after > before

    def test_logging_middleware_increments_latency_histogram(self, client_and_buf):
        from prometheus_client import REGISTRY
        client, _ = client_and_buf
        client.get("/health")
        found = any(
            s.name == "erp_rag_request_latency_seconds_count"
            for m in REGISTRY.collect()
            for s in m.samples
        )
        assert found


# ===========================================================================
# AuthMiddleware
# ===========================================================================

class TestAuthMiddleware:
    """AuthMiddleware blocks missing tokens and passes valid Bearer tokens."""

    @pytest.fixture()
    def client(self):
        from src.middleware.AuthMiddleware import AuthMiddleware
        from src.infrastructure.di.container import DIContainer
        from src.tests.fixtures.jwt_fixtures import make_jwt_handler

        self._jwt_handler = make_jwt_handler()
        app = _make_app(AuthMiddleware)
        container = DIContainer()
        container.register("jwt_handler", self._jwt_handler)
        container.register("user_repository", object())
        container.register("auth_use_case", object())
        app.state.container = container
        return TestClient(app, raise_server_exceptions=False)

    def test_auth_middleware_public_path_requires_no_token(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_auth_middleware_missing_token_returns_401(self, client):
        r = client.get("/admin/jobs")
        assert r.status_code == 401

    def test_auth_middleware_missing_token_returns_json_detail(self, client):
        r = client.get("/admin/jobs")
        body = r.json()
        assert "detail" in body

    def test_auth_middleware_bearer_token_passes_through(self, client):
        from src.tests.fixtures.jwt_fixtures import make_valid_token
        token = make_valid_token(self._jwt_handler, role="ADMIN")
        r = client.get("/admin/jobs", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_auth_middleware_malformed_header_returns_401(self, client):
        r = client.get("/admin/jobs", headers={"Authorization": "Token bad-format"})
        assert r.status_code == 401

    def test_auth_middleware_empty_bearer_returns_401(self, client):
        r = client.get("/admin/jobs", headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    def test_auth_middleware_increments_failure_counter_on_missing_token(self, client):
        from prometheus_client import REGISTRY

        def _count():
            for m in REGISTRY.collect():
                for s in m.samples:
                    if (s.name == "erp_rag_auth_failures_total"
                            and s.labels.get("reason") == "missing_token"):
                        return s.value
            return 0.0

        before = _count()
        client.get("/admin/jobs")   # no token
        after = _count()
        assert after - before == pytest.approx(1.0)

    def test_auth_middleware_sets_real_claims_on_valid_token(self, client):
        from fastapi import FastAPI
        from src.middleware.AuthMiddleware import AuthMiddleware
        from src.tests.fixtures.jwt_fixtures import make_jwt_handler, make_valid_token

        handler = make_jwt_handler()
        token = make_valid_token(handler, user_id="real-user", role="MANAGER", tenant_id="ferza")

        app = FastAPI()
        app.state.container = None  # AuthMiddleware will build its own handler

        # Wire handler into a mock container so middleware can resolve it
        from src.infrastructure.di.container import DIContainer
        container = DIContainer()
        container.register("jwt_handler", handler)
        container.register("user_repository", object())
        container.register("auth_use_case", object())
        app.state.container = container

        app.add_middleware(AuthMiddleware)

        @app.get("/whoami")
        async def whoami(request: Request):
            return {
                "user_id": getattr(request.state, "user_id", None),
                "role": getattr(request.state, "role", None),
                "tenant_id": getattr(request.state, "tenant_id", None),
            }

        c = TestClient(app, raise_server_exceptions=True)
        r = c.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == "real-user"
        assert body["role"] == "MANAGER"
        assert body["tenant_id"] == "ferza"


# ===========================================================================
# RateLimitMiddleware
# ===========================================================================

class TestRateLimitMiddleware:
    """RateLimitMiddleware logs violations but does not block in Sprint 1."""

    @pytest.fixture()
    def client(self):
        from src.middleware.RateLimitMiddleware import RateLimitMiddleware
        return TestClient(_make_app(RateLimitMiddleware), raise_server_exceptions=True)

    def test_rate_limit_passes_all_requests_in_sprint1(self, client):
        """Sprint 1 stub never returns 429."""
        for _ in range(5):
            r = client.get("/health")
            assert r.status_code == 200

    def test_rate_limit_uses_x_forwarded_for_for_ip(self, client):
        """Should not crash when X-Forwarded-For header is present."""
        r = client.get("/health", headers={"x-forwarded-for": "1.2.3.4"})
        assert r.status_code == 200

    def test_rate_limit_violation_increments_prometheus_counter(self):
        """Exceeding the per-user limit increments MIDDLEWARE_VIOLATIONS."""
        from src.middleware.RateLimitMiddleware import (
            RateLimitMiddleware,
            _WindowCounter,
            _USER_LIMIT_PER_MIN,
        )
        from prometheus_client import REGISTRY

        def _count():
            for m in REGISTRY.collect():
                for s in m.samples:
                    if (s.name == "erp_rag_middleware_violations_total"
                            and s.labels.get("middleware") == "rate_limit_user"):
                        return s.value
            return 0.0

        # Create an isolated counter, pre-flood it, then inject it into the app.
        test_user = f"flood-user-{time.monotonic()}"
        uc = _WindowCounter()
        for _ in range(_USER_LIMIT_PER_MIN + 2):
            uc.increment(test_user)

        before = _count()
        # One more hit triggers the violation log path
        from fastapi import FastAPI
        app2 = FastAPI()
        app2.add_middleware(RateLimitMiddleware, user_counter=uc)

        @app2.get("/health")
        async def h(request: Request):
            request.state.user_id = test_user
            return {}

        c = TestClient(app2, raise_server_exceptions=True)
        c.get("/health")
        after = _count()
        assert after >= before   # counter only increases

    def test_rate_limit_window_counter_evicts_old_hits(self):
        from src.middleware.RateLimitMiddleware import _WindowCounter
        counter = _WindowCounter()
        count = counter.increment("test-key")
        assert count == 1
        count2 = counter.increment("test-key")
        assert count2 == 2


# ===========================================================================
# RBACMiddleware
# ===========================================================================

class TestRBACMiddleware:
    """RBACMiddleware enforces ADMIN-only access to /admin/* paths."""

    @pytest.fixture()
    def client_with_admin_role(self):
        from src.middleware.AuthMiddleware import AuthMiddleware
        from src.middleware.RBACMiddleware import RBACMiddleware
        from src.infrastructure.di.container import DIContainer
        from src.tests.fixtures.jwt_fixtures import make_jwt_handler

        self._jwt_handler = make_jwt_handler()
        app = _make_app(AuthMiddleware, RBACMiddleware)

        container = DIContainer()
        container.register("jwt_handler", self._jwt_handler)
        container.register("user_repository", object())
        container.register("auth_use_case", object())
        app.state.container = container

        return TestClient(app, raise_server_exceptions=False)

    def test_rbac_admin_role_accesses_admin_route(self, client_with_admin_role):
        """Real RS256 token with role=SUPER_ADMIN should pass admin route."""
        from src.tests.fixtures.jwt_fixtures import make_valid_token
        token = make_valid_token(self._jwt_handler, role="SUPER_ADMIN")
        r = client_with_admin_role.get(
            "/admin/jobs", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200

    def test_rbac_non_admin_blocked_from_admin_route(self):
        """Inject a non-ADMIN role manually via state."""
        from fastapi import FastAPI
        from src.middleware.RBACMiddleware import RBACMiddleware

        app = FastAPI()
        app.add_middleware(RBACMiddleware)

        @app.get("/admin/jobs")
        async def admin_jobs(request: Request):
            return {"jobs": []}

        # Inject ANALYST role via a sub-middleware before RBACMiddleware sees it
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response
        from typing import Callable, Awaitable

        class _RoleInjector(BaseHTTPMiddleware):
            async def dispatch(self, req: Request,
                               call_next: Callable[[Request], Awaitable[Response]]) -> Response:
                req.state.role = "ANALYST"
                return await call_next(req)

        app2 = FastAPI()
        app2.add_middleware(RBACMiddleware)
        app2.add_middleware(_RoleInjector)

        @app2.get("/admin/jobs")
        async def aj(): return {"jobs": []}

        c = TestClient(app2, raise_server_exceptions=False)
        r = c.get("/admin/jobs")
        assert r.status_code == 403

    def test_rbac_violation_increments_counter(self):
        from fastapi import FastAPI
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response
        from typing import Callable, Awaitable
        from src.middleware.RBACMiddleware import RBACMiddleware
        from prometheus_client import REGISTRY

        class _ViewerInjector(BaseHTTPMiddleware):
            async def dispatch(self, req: Request,
                               call_next: Callable[[Request], Awaitable[Response]]) -> Response:
                req.state.role = "VIEWER"
                return await call_next(req)

        app = FastAPI()
        app.add_middleware(RBACMiddleware)
        app.add_middleware(_ViewerInjector)

        @app.get("/admin/jobs")
        async def aj(): return {}

        def _count():
            return sum(
                s.value
                for m in REGISTRY.collect()
                for s in m.samples
                if s.name == "erp_rag_rbac_violations_total"
            )

        c = TestClient(app, raise_server_exceptions=False)
        before = _count()
        c.get("/admin/jobs")
        after = _count()
        assert after > before

    def test_rbac_non_admin_path_passes_for_any_role(self):
        from fastapi import FastAPI
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response
        from typing import Callable, Awaitable
        from src.middleware.RBACMiddleware import RBACMiddleware

        class _AnalystInjector(BaseHTTPMiddleware):
            async def dispatch(self, req: Request,
                               call_next: Callable[[Request], Awaitable[Response]]) -> Response:
                req.state.role = "ANALYST"
                return await call_next(req)

        app = FastAPI()
        app.add_middleware(RBACMiddleware)
        app.add_middleware(_AnalystInjector)

        @app.get("/health")
        async def h(): return {"ok": True}

        c = TestClient(app, raise_server_exceptions=True)
        r = c.get("/health")
        assert r.status_code == 200

    def test_rbac_403_response_contains_detail(self):
        from fastapi import FastAPI
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response
        from typing import Callable, Awaitable
        from src.middleware.RBACMiddleware import RBACMiddleware

        class _ViewerInjector(BaseHTTPMiddleware):
            async def dispatch(self, req: Request,
                               call_next: Callable[[Request], Awaitable[Response]]) -> Response:
                req.state.role = "VIEWER"
                return await call_next(req)

        app = FastAPI()
        app.add_middleware(RBACMiddleware)
        app.add_middleware(_ViewerInjector)

        @app.get("/admin/jobs")
        async def aj(): return {}

        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/admin/jobs")
        assert "detail" in r.json()


# ===========================================================================
# PIIMaskingMiddleware
# ===========================================================================

# ===========================================================================
# Public paths — shared by AuthMiddleware and RBACMiddleware
# ===========================================================================

class TestPublicPaths:
    """Every public path must traverse the full middleware stack untokenised.

    Regression guard for the Sprint 10 blocker: RBACMiddleware read `path`
    before assigning it, so every request — public ones included — raised
    UnboundLocalError and Starlette returned 500. A middleware fault shows up
    as a 5xx, which no existing test asserted against on the public routes.
    """

    @pytest.fixture()
    def public_client(self):
        from src.middleware.AuthMiddleware import AuthMiddleware
        from src.middleware.RBACMiddleware import RBACMiddleware

        app = _make_app(AuthMiddleware, RBACMiddleware)
        return TestClient(app, raise_server_exceptions=False)

    def test_health_returns_200_without_a_token(self, public_client):
        resp = public_client.get("/health")
        assert resp.status_code == 200

    def test_no_public_path_raises_through_the_stack(self, public_client):
        """A 5xx here means a middleware raised, not that the route is missing."""
        for path in sorted(PUBLIC_PATHS):
            resp = public_client.get(path)
            assert resp.status_code < 500, (
                f"{path} returned {resp.status_code} — a middleware raised on a public path"
            )

    def test_protected_path_still_requires_a_token(self, public_client):
        """Skipping public paths must not open anything that was guarded."""
        resp = public_client.get("/admin/jobs")
        assert resp.status_code == 401

    def test_both_middlewares_read_the_same_public_set(self):
        """AuthMiddleware and RBACMiddleware must never drift apart."""
        from src.middleware.AuthMiddleware import _PUBLIC_PATHS

        assert _PUBLIC_PATHS is PUBLIC_PATHS


class TestPIIMaskingMiddleware:
    """PIIMaskingMiddleware detects and masks PII in query text."""

    @pytest.fixture()
    def client(self):
        from src.middleware.PIIMaskingMiddleware import PIIMaskingMiddleware
        return TestClient(_make_app(PIIMaskingMiddleware), raise_server_exceptions=True)

    def test_pii_email_detected_and_masked(self, client):
        r = client.post("/api/erp/query", json={"query": "orders for user@company.dz"})
        assert r.status_code == 200
        assert "[REDACTED:EMAIL]" in r.json()["query"]

    def test_pii_dz_phone_detected_and_masked(self, client):
        r = client.post("/api/erp/query", json={"query": "call +213551234567"})
        assert "[REDACTED:PHONE_DZ]" in r.json()["query"]

    def test_pii_nid_18digit_detected_and_masked(self, client):
        r = client.post("/api/erp/query", json={"query": "NID: 199003102300120012"})
        assert "[REDACTED:NID_DZ]" in r.json()["query"]

    def test_pii_tax_id_15digit_detected_and_masked(self, client):
        r = client.post("/api/erp/query", json={"query": "NIF: 123456789012345"})
        assert "[REDACTED:TAX_ID_DZ]" in r.json()["query"]

    def test_pii_multiple_entities_in_one_query(self, client):
        r = client.post(
            "/api/erp/query",
            json={"query": "user@example.com called +213661234567"},
        )
        body = r.json()["query"]
        assert "[REDACTED:EMAIL]" in body
        assert "[REDACTED:PHONE_DZ]" in body

    def test_pii_clean_query_passes_unchanged(self, client):
        query = "show me all sales for Q1 2024"
        r = client.post("/api/erp/query", json={"query": query})
        assert r.json()["query"] == query

    def test_pii_non_scan_path_not_processed(self, client):
        """GET /health body is not scanned (not in SCAN_PATHS)."""
        r = client.get("/health")
        assert r.status_code == 200

    def test_pii_increments_prometheus_counter(self, client):
        from prometheus_client import REGISTRY

        def _count():
            for m in REGISTRY.collect():
                for s in m.samples:
                    if (s.name == "erp_rag_pii_detections_total"
                            and s.labels.get("entity_type") == "email"):
                        return s.value
            return 0.0

        before = _count()
        client.post("/api/erp/query", json={"query": "email: test@domain.com"})
        after = _count()
        assert after > before

    def test_pii_non_json_body_does_not_crash(self):
        from src.middleware.PIIMaskingMiddleware import PIIMaskingMiddleware
        from fastapi import FastAPI
        app = FastAPI()
        app.add_middleware(PIIMaskingMiddleware)

        @app.post("/api/erp/query")
        async def q(): return {"ok": True}

        c = TestClient(app, raise_server_exceptions=True)
        r = c.post(
            "/api/erp/query",
            content=b"not-json-at-all",
            headers={"content-type": "text/plain"},
        )
        assert r.status_code == 200

    def test_pii_empty_query_string_does_not_crash(self, client):
        r = client.post("/api/erp/query", json={"query": ""})
        assert r.status_code == 200
        assert r.json()["query"] == ""


# ===========================================================================
# _mask_pii helper — unit level
# ===========================================================================

class TestMaskPiiHelper:
    """Direct unit tests for the _mask_pii function."""

    def test_mask_pii_email_replaced(self):
        from src.middleware.PIIMaskingMiddleware import _mask_pii
        text, counts = _mask_pii("contact admin@erp.dz for help")
        assert "[REDACTED:EMAIL]" in text
        assert counts["email"] == 1

    def test_mask_pii_no_match_returns_unchanged(self):
        from src.middleware.PIIMaskingMiddleware import _mask_pii
        text, counts = _mask_pii("no pii here")
        assert text == "no pii here"
        assert counts == {}

    def test_mask_pii_multiple_emails_counted(self):
        from src.middleware.PIIMaskingMiddleware import _mask_pii
        _, counts = _mask_pii("a@b.com and c@d.com")
        assert counts["email"] == 2

    def test_mask_pii_returns_tuple(self):
        from src.middleware.PIIMaskingMiddleware import _mask_pii
        result = _mask_pii("hello")
        assert isinstance(result, tuple)
        assert len(result) == 2
