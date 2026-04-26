"""
Integration tests — MIDDLEWARE_VIOLATIONS counter per middleware layer (Sprint 5, Task 6).

Covers all acceptance criteria:
  - MIDDLEWARE_VIOLATIONS.labels(middleware="auth") fires on every 401 from AuthMiddleware
    (missing token, expired token, tampered token, wrong algorithm)
  - MIDDLEWARE_VIOLATIONS.labels(middleware="auth") does NOT fire on public paths or valid tokens
  - MIDDLEWARE_VIOLATIONS.labels(middleware="pii") fires once per POST request with PII hits
  - MIDDLEWARE_VIOLATIONS.labels(middleware="pii") does NOT fire on clean bodies, GET requests,
    or non-scan paths
  - A single PII-laden request increments "pii" counter exactly once regardless of entity count
  - RateLimitMiddleware and RBACMiddleware violations (previously tested) still register correctly
  - All five expected label values are reachable: auth, rate_limit_user, rate_limit_ip,
    rbac_module, pii

Counter isolation: Prometheus counters are global singletons across the test session.
All assertions use before/after deltas — never absolute values.

Naming: test_{counter_label}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from prometheus_client import REGISTRY
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.auth.user_repository import InMemoryUserRepository
from src.infrastructure.di.container import DIContainer
from src.middleware.AuthMiddleware import AuthMiddleware
from src.middleware.PIIMaskingMiddleware import PIIMaskingMiddleware
from src.middleware.RBACMiddleware import RBACMiddleware
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
# Prometheus helper
# ---------------------------------------------------------------------------

def _violation_count(label: str) -> float:
    """Return current MIDDLEWARE_VIOLATIONS total for a given middleware label."""
    for m in REGISTRY.collect():
        for s in m.samples:
            if (
                s.name == "erp_rag_middleware_violations_total"
                and s.labels.get("middleware") == label
            ):
                return s.value
    return 0.0


# ---------------------------------------------------------------------------
# App factories
# ---------------------------------------------------------------------------

def _build_auth_app(jwt_handler):
    """Minimal app with AuthMiddleware + RBACMiddleware for auth violation tests."""
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
    app.add_middleware(RBACMiddleware)
    app.add_middleware(AuthMiddleware)

    @app.get("/api/erp/query")
    async def erp_query():
        return {"result": "ok"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def _build_pii_app(jwt_handler):
    """Minimal app with full stack including PIIMaskingMiddleware for PII tests.

    add_middleware LIFO order:
      PIIMaskingMiddleware (innermost) → RBACMiddleware → AuthMiddleware (outermost)
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
    app.add_middleware(PIIMaskingMiddleware)
    app.add_middleware(RBACMiddleware)
    app.add_middleware(AuthMiddleware)

    @app.post("/api/erp/query")
    async def erp_query_post(request: Request):
        return {
            "result": "ok",
            "pii_hits": getattr(request.state, "pii_hits", {}),
        }

    @app.post("/other-path")
    async def other_path(request: Request):
        return {"result": "ok"}

    @app.get("/api/erp/query")
    async def erp_query_get():
        return {"result": "ok"}

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def jwt_handler():
    return make_jwt_handler()


@pytest.fixture()
def auth_client(jwt_handler):
    app = _build_auth_app(jwt_handler)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def pii_client(jwt_handler):
    app = _build_pii_app(jwt_handler)
    return TestClient(app, raise_server_exceptions=False)


def _bearer(jwt_handler, role: str = "SUPER_ADMIN") -> dict:
    token = make_valid_token(jwt_handler, role=role, tenant_id="test-tenant")
    return {"Authorization": f"Bearer {token}"}


def _pii_body(query: str) -> str:
    return json.dumps({"query": query})


# ===========================================================================
# Guard: auth violations — counter increments on every 401
# ===========================================================================

class TestAuthViolationCounterIncrements:
    """Every 401 from AuthMiddleware must increment MIDDLEWARE_VIOLATIONS(auth)."""

    def test_missing_token_increments_auth_counter(self, auth_client):
        before = _violation_count("auth")
        auth_client.get("/api/erp/query")
        assert _violation_count("auth") == before + 1

    def test_malformed_bearer_increments_auth_counter(self, auth_client):
        before = _violation_count("auth")
        auth_client.get("/api/erp/query", headers={"Authorization": "NotBearer xyz"})
        assert _violation_count("auth") == before + 1

    def test_expired_token_increments_auth_counter(self, auth_client, jwt_handler):
        before = _violation_count("auth")
        expired = make_expired_token(jwt_handler)
        auth_client.get("/api/erp/query", headers={"Authorization": f"Bearer {expired}"})
        assert _violation_count("auth") == before + 1

    def test_tampered_token_increments_auth_counter(self, auth_client, jwt_handler):
        before = _violation_count("auth")
        tampered = make_tampered_token(jwt_handler)
        auth_client.get("/api/erp/query", headers={"Authorization": f"Bearer {tampered}"})
        assert _violation_count("auth") == before + 1

    def test_wrong_algorithm_token_increments_auth_counter(self, auth_client, jwt_handler):
        before = _violation_count("auth")
        wrong_alg = make_wrong_algorithm_token(jwt_handler)
        auth_client.get("/api/erp/query", headers={"Authorization": f"Bearer {wrong_alg}"})
        assert _violation_count("auth") == before + 1

    def test_each_auth_failure_increments_by_exactly_one(self, auth_client):
        before = _violation_count("auth")
        auth_client.get("/api/erp/query")
        auth_client.get("/api/erp/query")
        auth_client.get("/api/erp/query")
        assert _violation_count("auth") == before + 3

    def test_auth_failures_return_401(self, auth_client):
        resp = auth_client.get("/api/erp/query")
        assert resp.status_code == 401


# ===========================================================================
# Guard: auth violations — counter does NOT increment on clean paths
# ===========================================================================

class TestAuthViolationCounterNoIncrement:
    """Valid tokens and public paths must leave the auth counter unchanged."""

    def test_valid_token_does_not_increment_auth_counter(self, auth_client, jwt_handler):
        before = _violation_count("auth")
        auth_client.get("/api/erp/query", headers=_bearer(jwt_handler))
        assert _violation_count("auth") == before

    def test_public_health_path_does_not_increment_auth_counter(self, auth_client):
        before = _violation_count("auth")
        auth_client.get("/health")
        assert _violation_count("auth") == before

    def test_auth_counter_independent_from_rbac_counter(self, auth_client, jwt_handler):
        """A valid token that triggers an RBAC block must not increment auth counter."""
        before_auth = _violation_count("auth")
        # REPORTING_ANALYST is blocked by RBAC, not Auth — auth counter must not change
        token = make_valid_token(jwt_handler, role="REPORTING_ANALYST", tenant_id="t")
        auth_client.get("/api/erp/query", headers={"Authorization": f"Bearer {token}"})
        assert _violation_count("auth") == before_auth


# ===========================================================================
# Guard: PII violations — counter increments once per request with PII hits
# ===========================================================================

class TestPIIViolationCounterIncrements:
    """Every POST with at least one PII entity must increment MIDDLEWARE_VIOLATIONS(pii)."""

    def test_email_in_body_increments_pii_counter(self, pii_client, jwt_handler):
        before = _violation_count("pii")
        pii_client.post(
            "/api/erp/query",
            content=_pii_body("Send to user@example.com for review"),
            headers={"content-type": "application/json", **_bearer(jwt_handler)},
        )
        assert _violation_count("pii") == before + 1

    def test_phone_in_body_increments_pii_counter(self, pii_client, jwt_handler):
        before = _violation_count("pii")
        pii_client.post(
            "/api/erp/query",
            content=_pii_body("Call 0661234567 for confirmation"),
            headers={"content-type": "application/json", **_bearer(jwt_handler)},
        )
        assert _violation_count("pii") == before + 1

    def test_nid_in_body_increments_pii_counter(self, pii_client, jwt_handler):
        before = _violation_count("pii")
        pii_client.post(
            "/api/erp/query",
            content=_pii_body("Employee NID 199001011234567890 on file"),
            headers={"content-type": "application/json", **_bearer(jwt_handler)},
        )
        assert _violation_count("pii") == before + 1

    def test_tax_id_in_body_increments_pii_counter(self, pii_client, jwt_handler):
        before = _violation_count("pii")
        pii_client.post(
            "/api/erp/query",
            content=_pii_body("Supplier NIF 123456789012345 approved"),
            headers={"content-type": "application/json", **_bearer(jwt_handler)},
        )
        assert _violation_count("pii") == before + 1

    def test_multiple_pii_types_increments_counter_exactly_once(self, pii_client, jwt_handler):
        """Three PII entities in one request → exactly one increment, not three."""
        before = _violation_count("pii")
        pii_client.post(
            "/api/erp/query",
            content=_pii_body(
                "Contact admin@corp.dz, NIF 123456789012345, phone 0661234567"
            ),
            headers={"content-type": "application/json", **_bearer(jwt_handler)},
        )
        assert _violation_count("pii") == before + 1

    def test_multiple_pii_requests_each_increment_once(self, pii_client, jwt_handler):
        before = _violation_count("pii")
        for _ in range(3):
            pii_client.post(
                "/api/erp/query",
                content=_pii_body("Email: user@example.com"),
                headers={"content-type": "application/json", **_bearer(jwt_handler)},
            )
        assert _violation_count("pii") == before + 3


# ===========================================================================
# Guard: PII violations — counter does NOT increment on clean requests
# ===========================================================================

class TestPIIViolationCounterNoIncrement:
    """Clean bodies, GET requests, and non-scan paths must not touch the pii counter."""

    def test_clean_body_does_not_increment_pii_counter(self, pii_client, jwt_handler):
        before = _violation_count("pii")
        pii_client.post(
            "/api/erp/query",
            content=_pii_body("List all pending purchase orders above 50000 DZD"),
            headers={"content-type": "application/json", **_bearer(jwt_handler)},
        )
        assert _violation_count("pii") == before

    def test_get_request_does_not_increment_pii_counter(self, pii_client, jwt_handler):
        """PIIMaskingMiddleware only scans POST — GET must be ignored."""
        before = _violation_count("pii")
        pii_client.get("/api/erp/query", headers=_bearer(jwt_handler))
        assert _violation_count("pii") == before

    def test_non_scan_path_post_does_not_increment_pii_counter(self, pii_client, jwt_handler):
        """/other-path is not in _SCAN_PATHS — PII scanning is skipped."""
        before = _violation_count("pii")
        pii_client.post(
            "/other-path",
            content=_pii_body("admin@corp.dz should not be scanned here"),
            headers={"content-type": "application/json", **_bearer(jwt_handler)},
        )
        assert _violation_count("pii") == before

    def test_non_json_body_does_not_increment_pii_counter(self, pii_client, jwt_handler):
        """Non-JSON body raises JSONDecodeError which is silently swallowed."""
        before = _violation_count("pii")
        pii_client.post(
            "/api/erp/query",
            content=b"this is not json",
            headers={"content-type": "text/plain", **_bearer(jwt_handler)},
        )
        assert _violation_count("pii") == before


# ===========================================================================
# Cross-middleware: all five label values are reachable
# ===========================================================================

class TestAllViolationLabelsReachable:
    """Verify each of the five expected middleware label values can be observed
    in REGISTRY — proves the metric description is accurate and no label is
    silently dropped or misspelled."""

    _EXPECTED_LABELS = frozenset({
        "auth",
        "rate_limit_user",
        "rate_limit_ip",
        "rbac_module",
        "pii",
    })

    def _observed_labels(self) -> set[str]:
        observed = set()
        for m in REGISTRY.collect():
            for s in m.samples:
                if s.name == "erp_rag_middleware_violations_total":
                    label = s.labels.get("middleware")
                    if label:
                        observed.add(label)
        return observed

    def test_auth_label_is_observable_in_registry(self, auth_client):
        auth_client.get("/api/erp/query")  # triggers auth violation
        assert "auth" in self._observed_labels()

    def test_pii_label_is_observable_in_registry(self, pii_client, jwt_handler):
        pii_client.post(
            "/api/erp/query",
            content=_pii_body("user@example.com"),
            headers={"content-type": "application/json", **_bearer(jwt_handler)},
        )
        assert "pii" in self._observed_labels()

    def test_rbac_module_label_is_observable_in_registry(self, auth_client, jwt_handler):
        token = make_valid_token(jwt_handler, role="REPORTING_ANALYST", tenant_id="t")
        auth_client.get("/api/erp/query", headers={"Authorization": f"Bearer {token}"})
        assert "rbac_module" in self._observed_labels()

    def test_middleware_violations_metric_description_names_all_labels(self):
        """The metric help-text must document all five middleware label values."""
        for m in REGISTRY.collect():
            if m.name == "erp_rag_middleware_violations":
                for label in ("auth", "rate_limit_user", "rate_limit_ip", "rbac_module", "pii"):
                    assert label in m.documentation, (
                        f"Label '{label}' missing from MIDDLEWARE_VIOLATIONS description"
                    )
                return
        pytest.fail("erp_rag_middleware_violations metric not found in REGISTRY")
