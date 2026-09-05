"""
Integration tests — middleware ordering: Auth and RBAC rejections never reach SQL pipeline.

Sprint 5, Task 7.

Acceptance criteria:
  - Request with no/invalid/expired/tampered token → 401 from AuthMiddleware;
    the SQL pipeline route handler is never called.
  - Request from a role blocked by RBAC (REPORTING_ANALYST) → 403;
    the SQL pipeline route handler is never called.
  - A valid, permitted request → route handler IS called and returns 200
    (proves the gate is the middleware, not a misconfigured route).
  - the sql_generate stage latency and SQL_STAGE3_ROWS metrics do not change
    when Auth or RBAC blocks the request.

Stack under test (add_middleware LIFO → request traversal order):
    Request → AuthMiddleware → RBACMiddleware → route handler

Counter isolation: all Prometheus assertions use before/after deltas.
Sentinel isolation: _sql_handler_calls list is reset per test via fixture.

Naming: test_{blocking_layer}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Generator

import pytest
from fastapi import FastAPI, Request
from prometheus_client import REGISTRY
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.auth.user_repository import InMemoryUserRepository
from src.infrastructure.di.container import DIContainer
from src.middleware.AuthMiddleware import AuthMiddleware
from src.middleware.RBACMiddleware import RBACMiddleware
from src.observability.prometheus_metrics import QUERY_STAGE_LATENCY_MS, SQL_STAGE3_ROWS
from src.observability.stage_timer import Stage
from src.tests.fixtures.jwt_fixtures import (
    make_expired_token,
    make_jwt_handler,
    make_tampered_token,
    make_valid_token,
    make_wrong_algorithm_token,
)
from src.infrastructure.di.factory import build_query_chain
from src.use_cases.auth_user import AuthUseCase


# ---------------------------------------------------------------------------
# Sentinel — tracks whether the SQL pipeline handler was reached
# ---------------------------------------------------------------------------

# Mutable list used as a call log; reset between tests by the fixture below.
_sql_handler_calls: list[str] = []


# ---------------------------------------------------------------------------
# Prometheus helpers
# ---------------------------------------------------------------------------

def _sql_stage1_sample_count() -> float:
    """Observation count for the sql_generate stage (rises on every observe())."""
    for m in REGISTRY.collect():
        if m.name == "erp_rag_query_stage_latency_ms":
            for s in m.samples:
                if (
                    s.name == "erp_rag_query_stage_latency_ms_count"
                    and s.labels.get("stage") == Stage.SQL_GENERATE.value
                ):
                    return s.value
    return 0.0


def _sql_stage3_sample_count() -> float:
    """Return the current _count sample of SQL_STAGE3_ROWS (increments on every observe())."""
    for m in REGISTRY.collect():
        if m.name == "erp_rag_sql_stage3_rows_returned":
            for s in m.samples:
                if s.name == "erp_rag_sql_stage3_rows_returned_count":
                    return s.value
    return 0.0


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _build_app(jwt_handler) -> FastAPI:
    """Build minimal app with AuthMiddleware → RBACMiddleware → SQL handler.

    The /api/erp/query handler simulates what the SQL pipeline would do:
      - appends a sentinel entry to _sql_handler_calls
      - observes both the sql_generate stage latency and SQL_STAGE3_ROWS

    If either middleware blocks the request, the handler is never reached,
    so _sql_handler_calls stays empty and the metrics stay flat.
    """
    user_repo = InMemoryUserRepository()
    auth_use_case = AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler)

    container = DIContainer()
    container.register("jwt_handler", jwt_handler)
    container.register("user_repository", user_repo)
    container.register("auth_use_case", auth_use_case)
    build_query_chain(container)
    container.validate()

    app = FastAPI()
    app.state.container = container

    # LIFO: RBACMiddleware added first → AuthMiddleware wraps it (outermost)
    app.add_middleware(RBACMiddleware)
    app.add_middleware(AuthMiddleware)

    @app.get("/api/erp/query")
    async def sql_pipeline_handler(request: Request):
        """Simulated SQL pipeline entry point."""
        _sql_handler_calls.append(request.state.user_id)
        # Simulate Stage 1 and Stage 3 metric observations
        QUERY_STAGE_LATENCY_MS.labels(stage=Stage.SQL_GENERATE.value).observe(50.0)
        SQL_STAGE3_ROWS.observe(2)
        return {"result": "ok", "rows": 2}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def jwt_handler():
    return make_jwt_handler()


@pytest.fixture()
def client(jwt_handler) -> TestClient:
    return TestClient(_build_app(jwt_handler), raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def reset_sentinel() -> Generator[None, None, None]:
    """Clear the SQL handler call log before and after every test."""
    _sql_handler_calls.clear()
    yield
    _sql_handler_calls.clear()


def _bearer(jwt_handler, role: str = "SUPER_ADMIN", tenant_id: str = "t1") -> dict:
    token = make_valid_token(jwt_handler, role=role, tenant_id=tenant_id)
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Baseline: valid request DOES reach the SQL handler
# ===========================================================================

class TestValidRequestReachesSQLHandler:
    """Confirm the handler is reachable under normal conditions.
    Proves that failures in other test classes are caused by middleware, not config."""

    def test_valid_super_admin_token_reaches_sql_handler(self, client, jwt_handler):
        resp = client.get("/api/erp/query", headers=_bearer(jwt_handler))
        assert resp.status_code == 200
        assert len(_sql_handler_calls) == 1

    def test_valid_request_increments_sql_metrics(self, client, jwt_handler):
        before_s1 = _sql_stage1_sample_count()
        before_s3 = _sql_stage3_sample_count()
        client.get("/api/erp/query", headers=_bearer(jwt_handler))
        assert _sql_stage1_sample_count() == before_s1 + 1
        assert _sql_stage3_sample_count() == before_s3 + 1


# ===========================================================================
# Auth layer blocks — SQL handler must never be reached
# ===========================================================================

class TestAuthBlockNeverReachesSQLHandler:
    """401 from AuthMiddleware must short-circuit before the SQL route handler."""

    def test_missing_token_returns_401_and_handler_not_called(self, client):
        resp = client.get("/api/erp/query")
        assert resp.status_code == 401
        assert _sql_handler_calls == []

    def test_malformed_bearer_returns_401_and_handler_not_called(self, client):
        resp = client.get("/api/erp/query", headers={"Authorization": "Token xyz"})
        assert resp.status_code == 401
        assert _sql_handler_calls == []

    def test_expired_token_returns_401_and_handler_not_called(self, client, jwt_handler):
        token = make_expired_token(jwt_handler)
        resp = client.get("/api/erp/query", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert _sql_handler_calls == []

    def test_tampered_token_returns_401_and_handler_not_called(self, client, jwt_handler):
        token = make_tampered_token(jwt_handler)
        resp = client.get("/api/erp/query", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert _sql_handler_calls == []

    def test_wrong_algorithm_token_returns_401_and_handler_not_called(self, client, jwt_handler):
        token = make_wrong_algorithm_token(jwt_handler)
        resp = client.get("/api/erp/query", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert _sql_handler_calls == []


class TestAuthBlockDoesNotIncrementSQLMetrics:
    """Stage latency and SQL_STAGE3_ROWS must stay flat when Auth blocks."""

    def test_missing_token_sql_stage1_metric_unchanged(self, client):
        before = _sql_stage1_sample_count()
        client.get("/api/erp/query")
        assert _sql_stage1_sample_count() == before

    def test_missing_token_sql_stage3_metric_unchanged(self, client):
        before = _sql_stage3_sample_count()
        client.get("/api/erp/query")
        assert _sql_stage3_sample_count() == before

    def test_expired_token_sql_metrics_unchanged(self, client, jwt_handler):
        token = make_expired_token(jwt_handler)
        before_s1 = _sql_stage1_sample_count()
        before_s3 = _sql_stage3_sample_count()
        client.get("/api/erp/query", headers={"Authorization": f"Bearer {token}"})
        assert _sql_stage1_sample_count() == before_s1
        assert _sql_stage3_sample_count() == before_s3

    def test_tampered_token_sql_metrics_unchanged(self, client, jwt_handler):
        token = make_tampered_token(jwt_handler)
        before_s1 = _sql_stage1_sample_count()
        before_s3 = _sql_stage3_sample_count()
        client.get("/api/erp/query", headers={"Authorization": f"Bearer {token}"})
        assert _sql_stage1_sample_count() == before_s1
        assert _sql_stage3_sample_count() == before_s3

    def test_multiple_auth_failures_sql_metrics_stay_flat(self, client):
        before_s1 = _sql_stage1_sample_count()
        before_s3 = _sql_stage3_sample_count()
        for _ in range(5):
            client.get("/api/erp/query")
        assert _sql_stage1_sample_count() == before_s1
        assert _sql_stage3_sample_count() == before_s3


# ===========================================================================
# RBAC layer blocks — SQL handler must never be reached
# ===========================================================================

class TestRBACBlockNeverReachesSQLHandler:
    """403 from RBACMiddleware must short-circuit before the SQL route handler.

    REPORTING_ANALYST is the canonical SQL-denied role per § 8.6.
    """

    def test_reporting_analyst_returns_403_and_handler_not_called(self, client, jwt_handler):
        headers = _bearer(jwt_handler, role="REPORTING_ANALYST")
        resp = client.get("/api/erp/query", headers=headers)
        assert resp.status_code == 403
        assert _sql_handler_calls == []

    def test_rbac_block_response_body_contains_detail(self, client, jwt_handler):
        headers = _bearer(jwt_handler, role="REPORTING_ANALYST")
        resp = client.get("/api/erp/query", headers=headers)
        assert "detail" in resp.json()
        assert resp.json()["detail"] != ""


class TestRBACBlockDoesNotIncrementSQLMetrics:
    """SQL metrics must stay flat when RBAC blocks the request."""

    def test_reporting_analyst_sql_stage1_metric_unchanged(self, client, jwt_handler):
        headers = _bearer(jwt_handler, role="REPORTING_ANALYST")
        before = _sql_stage1_sample_count()
        client.get("/api/erp/query", headers=headers)
        assert _sql_stage1_sample_count() == before

    def test_reporting_analyst_sql_stage3_metric_unchanged(self, client, jwt_handler):
        headers = _bearer(jwt_handler, role="REPORTING_ANALYST")
        before = _sql_stage3_sample_count()
        client.get("/api/erp/query", headers=headers)
        assert _sql_stage3_sample_count() == before

    def test_multiple_rbac_failures_sql_metrics_stay_flat(self, client, jwt_handler):
        headers = _bearer(jwt_handler, role="REPORTING_ANALYST")
        before_s1 = _sql_stage1_sample_count()
        before_s3 = _sql_stage3_sample_count()
        for _ in range(3):
            client.get("/api/erp/query", headers=headers)
        assert _sql_stage1_sample_count() == before_s1
        assert _sql_stage3_sample_count() == before_s3


# ===========================================================================
# Stack ordering proof — Auth fires before RBAC
# ===========================================================================

class TestMiddlewareOrdering:
    """Prove that AuthMiddleware is evaluated before RBACMiddleware.

    A request that is both unauthenticated AND would be RBAC-blocked
    must return 401 (Auth), not 403 (RBAC) — Auth is outermost.
    """

    def test_unauthenticated_request_gets_401_not_403(self, client):
        """No token → Auth fires first → 401; RBAC never evaluates."""
        resp = client.get("/api/erp/query")
        assert resp.status_code == 401
        # Confirm it is NOT a 403 (which would mean RBAC ran first)
        assert resp.status_code != 403

    def test_public_health_path_bypasses_both_middleware_layers(self, client):
        """/health is in AuthMiddleware._PUBLIC_PATHS → no token needed → 200."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert _sql_handler_calls == []
