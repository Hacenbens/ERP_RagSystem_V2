"""
Integration tests — RBACMiddleware module guard (Sprint 5, Task 3).

Covers all acceptance criteria:
  - REPORTING_ANALYST blocked on /api/erp/query (SQL path) → 403
  - SUPER_ADMIN passes all modules → 200
  - Role with request.state.erp_module set to denied module → 403
    with {"detail": "Module '<module>' not permitted for role '<role>'."}
  - Role with request.state.erp_table set to denied table → 403
  - MIDDLEWARE_VIOLATIONS.labels(middleware="rbac_module").inc() fires

Middleware stack in test app (request order):
  AuthMiddleware → _StateInjector → RBACMiddleware → route

Naming: test_{guard}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Awaitable, Callable

import pytest
from fastapi import FastAPI, Request
from prometheus_client import REGISTRY
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.auth.jwt_handler import JWTHandler
from src.infrastructure.auth.user_repository import InMemoryUserRepository
from src.infrastructure.di.container import DIContainer
from src.middleware.AuthMiddleware import AuthMiddleware
from src.middleware.RBACMiddleware import RBACMiddleware
from src.tests.fixtures.jwt_fixtures import make_jwt_handler, make_valid_token
from src.use_cases.auth_user import AuthUseCase


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

def _make_state_injector(**state_kwargs: object) -> type:
    """Return a middleware class that injects given kwargs into request.state.

    Designed to sit between AuthMiddleware and RBACMiddleware so the role
    guard sees the injected erp_module / erp_table before deciding.
    """
    class _StateInjector(BaseHTTPMiddleware):
        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            for key, val in state_kwargs.items():
                setattr(request.state, key, val)
            return await call_next(request)

    return _StateInjector


def _build_app(
    jwt_handler: JWTHandler,
    **state_kwargs: object,
) -> FastAPI:
    """Build a minimal FastAPI app with the full RBAC middleware stack.

    Middleware order (add_middleware is LIFO, last added = outermost):
      app.add_middleware(RBACMiddleware)    → inner
      app.add_middleware(_StateInjector)   → middle  (injects before RBAC)
      app.add_middleware(AuthMiddleware)   → outer   (sets role first)

    Request processing: Auth → StateInjector → RBAC → route
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

    app.add_middleware(RBACMiddleware)
    if state_kwargs:
        app.add_middleware(_make_state_injector(**state_kwargs))  # type: ignore[arg-type]
    app.add_middleware(AuthMiddleware)

    @app.get("/api/erp/query")
    async def erp_query(request: Request):
        return {"result": "ok", "role": getattr(request.state, "role", None)}

    @app.get("/admin/status")
    async def admin_status(request: Request):
        return {"status": "healthy"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def jwt_handler() -> JWTHandler:
    return make_jwt_handler()


def _token(jwt_handler: JWTHandler, role: str) -> dict:
    tok = make_valid_token(jwt_handler, role=role, tenant_id="test-tenant")
    return {"Authorization": f"Bearer {tok}"}


def _client(jwt_handler: JWTHandler, **state_kwargs: object) -> TestClient:
    app = _build_app(jwt_handler, **state_kwargs)
    return TestClient(app, raise_server_exceptions=False)


def _rbac_module_violation_count() -> float:
    for m in REGISTRY.collect():
        for s in m.samples:
            if (
                s.name == "erp_rag_middleware_violations_total"
                and s.labels.get("middleware") == "rbac_module"
            ):
                return s.value
    return 0.0


# ===========================================================================
# Guard 1 — Admin route (SUPER_ADMIN only)
# ===========================================================================

class TestAdminRouteGuard:
    """Sanity check that the admin guard still works after Sprint 5 changes."""

    def test_super_admin_reaches_admin_route(self, jwt_handler):
        client = _client(jwt_handler)
        resp = client.get("/admin/status", headers=_token(jwt_handler, "SUPER_ADMIN"))
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", [
        "PRODUCT_MANAGER", "FINANCE_MANAGER", "REPORTING_ANALYST",
    ])
    def test_non_super_admin_blocked_from_admin_route(self, jwt_handler, role):
        client = _client(jwt_handler)
        resp = client.get("/admin/status", headers=_token(jwt_handler, role))
        assert resp.status_code == 403
        assert "detail" in resp.json()


# ===========================================================================
# Guard 2a — REPORTING_ANALYST always blocked on SQL path
# ===========================================================================

class TestReportingAnalystSQLBlock:
    """REPORTING_ANALYST must be denied on /api/erp/query regardless of module state."""

    def test_reporting_analyst_blocked_on_sql_path_no_state(self, jwt_handler):
        client = _client(jwt_handler)
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "REPORTING_ANALYST")
        )
        assert resp.status_code == 403

    def test_reporting_analyst_403_detail_mentions_sql_path(self, jwt_handler):
        client = _client(jwt_handler)
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "REPORTING_ANALYST")
        )
        detail = resp.json()["detail"]
        assert "REPORTING_ANALYST" in detail

    def test_reporting_analyst_blocked_even_with_erp_module_set(self, jwt_handler):
        """REPORTING_ANALYST check happens before module check — must still deny."""
        client = _client(jwt_handler, erp_module="inventory")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "REPORTING_ANALYST")
        )
        assert resp.status_code == 403

    def test_reporting_analyst_blocked_even_with_erp_table_set(self, jwt_handler):
        client = _client(jwt_handler, erp_table="inventory")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "REPORTING_ANALYST")
        )
        assert resp.status_code == 403

    def test_reporting_analyst_can_access_health(self, jwt_handler):
        """SQL guard applies only to /api/erp/query — health must pass."""
        client = _client(jwt_handler)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_unauthenticated_request_returns_401_not_403(self, jwt_handler):
        """Auth runs before RBAC — no token → 401, not 403."""
        client = _client(jwt_handler)
        resp = client.get("/api/erp/query")
        assert resp.status_code == 401


# ===========================================================================
# Guard 2b — erp_module in request.state
# ===========================================================================

class TestModuleStateGuard:
    """When request.state.erp_module is set, RBAC checks module-level permission."""

    def test_super_admin_passes_any_module(self, jwt_handler):
        client = _client(jwt_handler, erp_module="finance")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "SUPER_ADMIN")
        )
        assert resp.status_code == 200

    def test_finance_manager_passes_finance_module(self, jwt_handler):
        client = _client(jwt_handler, erp_module="finance")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "FINANCE_MANAGER")
        )
        assert resp.status_code == 200

    def test_product_manager_blocked_on_finance_module(self, jwt_handler):
        """PRODUCT_MANAGER has no FINANCE module — must receive 403."""
        client = _client(jwt_handler, erp_module="finance")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "PRODUCT_MANAGER")
        )
        assert resp.status_code == 403

    def test_product_manager_blocked_detail_message(self, jwt_handler):
        """Detail must name the denied module and the requesting role."""
        client = _client(jwt_handler, erp_module="finance")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "PRODUCT_MANAGER")
        )
        detail = resp.json()["detail"]
        assert "finance" in detail
        assert "PRODUCT_MANAGER" in detail

    def test_warehouse_operator_blocked_on_crm_module(self, jwt_handler):
        client = _client(jwt_handler, erp_module="crm")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "WAREHOUSE_OPERATOR")
        )
        assert resp.status_code == 403

    def test_warehouse_operator_passes_warehouse_module(self, jwt_handler):
        client = _client(jwt_handler, erp_module="warehouse")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "WAREHOUSE_OPERATOR")
        )
        assert resp.status_code == 200

    def test_unknown_module_name_denied_for_any_role(self, jwt_handler):
        client = _client(jwt_handler, erp_module="ghost_module")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "FINANCE_MANAGER")
        )
        assert resp.status_code == 403

    def test_product_manager_passes_inventory_module(self, jwt_handler):
        client = _client(jwt_handler, erp_module="inventory")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "PRODUCT_MANAGER")
        )
        assert resp.status_code == 200

    def test_logistics_agent_blocked_on_finance_module(self, jwt_handler):
        client = _client(jwt_handler, erp_module="finance")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "LOGISTICS_AGENT")
        )
        assert resp.status_code == 403


# ===========================================================================
# Guard 2c — erp_table in request.state
# ===========================================================================

class TestTableStateGuard:
    """When request.state.erp_table is set, RBAC resolves table → module."""

    def test_finance_manager_passes_on_invoice_table(self, jwt_handler):
        client = _client(jwt_handler, erp_table="invoices")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "FINANCE_MANAGER")
        )
        assert resp.status_code == 200

    def test_product_manager_blocked_on_finance_table(self, jwt_handler):
        """invoices → finance module → PRODUCT_MANAGER has no FINANCE SQL access."""
        client = _client(jwt_handler, erp_table="invoices")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "PRODUCT_MANAGER")
        )
        assert resp.status_code == 403

    def test_product_manager_blocked_table_detail_message(self, jwt_handler):
        """Error detail must name the resolved module, not the raw table."""
        client = _client(jwt_handler, erp_table="invoices")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "PRODUCT_MANAGER")
        )
        detail = resp.json()["detail"]
        assert "finance" in detail          # resolved module label
        assert "PRODUCT_MANAGER" in detail

    def test_product_manager_passes_on_inventory_table(self, jwt_handler):
        client = _client(jwt_handler, erp_table="inventory")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "PRODUCT_MANAGER")
        )
        assert resp.status_code == 200

    def test_warehouse_operator_blocked_on_inventory_table(self, jwt_handler):
        """WAREHOUSE_OPERATOR has INVENTORY as RAG_ONLY — SQL denied."""
        client = _client(jwt_handler, erp_table="inventory")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "WAREHOUSE_OPERATOR")
        )
        assert resp.status_code == 403

    def test_super_admin_passes_any_table(self, jwt_handler):
        for table in ["invoices", "inventory", "shipments", "employees"]:
            client = _client(jwt_handler, erp_table=table)
            resp = client.get(
                "/api/erp/query", headers=_token(jwt_handler, "SUPER_ADMIN")
            )
            assert resp.status_code == 200, (
                f"SUPER_ADMIN must pass table '{table}', got {resp.status_code}"
            )

    def test_crm_agent_blocked_on_finance_table(self, jwt_handler):
        client = _client(jwt_handler, erp_table="payroll")
        resp = client.get(
            "/api/erp/query", headers=_token(jwt_handler, "CRM_AGENT")
        )
        assert resp.status_code == 403


# ===========================================================================
# Prometheus counter — MIDDLEWARE_VIOLATIONS fires on every block
# ===========================================================================

class TestPrometheusCounterOnBlock:
    """MIDDLEWARE_VIOLATIONS.labels(middleware='rbac_module') must increment."""

    def test_reporting_analyst_block_increments_counter(self, jwt_handler):
        client = _client(jwt_handler)
        before = _rbac_module_violation_count()
        client.get("/api/erp/query", headers=_token(jwt_handler, "REPORTING_ANALYST"))
        after = _rbac_module_violation_count()
        assert after > before

    def test_module_denial_increments_counter(self, jwt_handler):
        client = _client(jwt_handler, erp_module="finance")
        before = _rbac_module_violation_count()
        client.get("/api/erp/query", headers=_token(jwt_handler, "PRODUCT_MANAGER"))
        after = _rbac_module_violation_count()
        assert after > before

    def test_table_denial_increments_counter(self, jwt_handler):
        client = _client(jwt_handler, erp_table="invoices")
        before = _rbac_module_violation_count()
        client.get("/api/erp/query", headers=_token(jwt_handler, "PRODUCT_MANAGER"))
        after = _rbac_module_violation_count()
        assert after > before

    def test_successful_request_does_not_increment_counter(self, jwt_handler):
        client = _client(jwt_handler, erp_module="finance")
        before = _rbac_module_violation_count()
        client.get("/api/erp/query", headers=_token(jwt_handler, "FINANCE_MANAGER"))
        after = _rbac_module_violation_count()
        assert after == before
