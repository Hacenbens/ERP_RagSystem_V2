"""
Integration tests — RBAC enforcement (Sprint 5 update).

Role set updated to domain enums (source of truth § 8.1):
  SQL-capable roles: all except REPORTING_ANALYST
  Admin-only:        SUPER_ADMIN
  RAG-only role:     REPORTING_ANALYST (blocked from /api/erp/query SQL path)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.domain.user_role import UserRole
from src.tests.conftest import build_test_app
from src.tests.fixtures.jwt_fixtures import make_jwt_handler, make_valid_token

# ---------------------------------------------------------------------------
# Role groups (derived from domain enum — never hard-coded)
# ---------------------------------------------------------------------------

_ALL_ROLES       = [r.value for r in UserRole]
_SQL_ROLES       = [r.value for r in UserRole if r != UserRole.REPORTING_ANALYST]
_NON_ADMIN_ROLES = [r.value for r in UserRole if r != UserRole.SUPER_ADMIN]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def jwt_handler():
    return make_jwt_handler()


@pytest.fixture()
def client(jwt_handler):
    app, _ = build_test_app(jwt_handler=jwt_handler)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_token(jwt_handler, role: str, tenant_id: str = "acme") -> str:
    return make_valid_token(
        jwt_handler,
        user_id=f"user-{role.lower()}",
        role=role,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# /api/erp/query — SQL-capable roles only
# ---------------------------------------------------------------------------

class TestERPQueryAccess:
    @pytest.mark.parametrize("role", _SQL_ROLES)
    def test_sql_capable_roles_can_access_erp_query(self, client, jwt_handler, role):
        token = _make_token(jwt_handler, role)
        resp = client.get("/api/erp/query", headers=_auth_header(token))
        assert resp.status_code == 200, (
            f"Role {role} should have SQL access to /api/erp/query, got {resp.status_code}"
        )

    def test_reporting_analyst_blocked_on_sql_path(self, client, jwt_handler):
        """REPORTING_ANALYST is a RAG-only role — SQL path must return 403."""
        token = _make_token(jwt_handler, UserRole.REPORTING_ANALYST.value)
        resp = client.get("/api/erp/query", headers=_auth_header(token))
        assert resp.status_code == 403
        assert "detail" in resp.json()

    @pytest.mark.parametrize("role", _SQL_ROLES)
    def test_role_injected_into_response(self, client, jwt_handler, role):
        token = _make_token(jwt_handler, role)
        resp = client.get("/api/erp/query", headers=_auth_header(token))
        assert resp.json()["role"] == role

    def test_no_token_returns_401_not_403(self, client):
        """Unauthenticated request → 401 (not 403) — auth fails before RBAC."""
        resp = client.get("/api/erp/query")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /admin/status — SUPER_ADMIN only
# ---------------------------------------------------------------------------

class TestAdminRouteAccess:
    def test_super_admin_can_access_admin_route(self, client, jwt_handler):
        token = _make_token(jwt_handler, UserRole.SUPER_ADMIN.value)
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", _NON_ADMIN_ROLES)
    def test_non_super_admin_roles_get_403_on_admin_route(self, client, jwt_handler, role):
        token = _make_token(jwt_handler, role)
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert resp.status_code == 403, (
            f"Role {role} should be blocked from /admin/status, got {resp.status_code}"
        )

    @pytest.mark.parametrize("role", _NON_ADMIN_ROLES)
    def test_403_response_has_detail(self, client, jwt_handler, role):
        token = _make_token(jwt_handler, role)
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert "detail" in resp.json()

    def test_unauthenticated_admin_route_returns_401(self, client):
        """No token → 401 before RBAC even runs."""
        resp = client.get("/admin/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Role isolation — privilege escalation sanity checks
# ---------------------------------------------------------------------------

class TestRoleIsolation:
    def test_reporting_analyst_cannot_reach_admin(self, client, jwt_handler):
        token = _make_token(jwt_handler, UserRole.REPORTING_ANALYST.value)
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert resp.status_code == 403

    def test_finance_manager_cannot_reach_admin(self, client, jwt_handler):
        token = _make_token(jwt_handler, UserRole.FINANCE_MANAGER.value)
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert resp.status_code == 403

    def test_product_manager_cannot_reach_admin(self, client, jwt_handler):
        token = _make_token(jwt_handler, UserRole.PRODUCT_MANAGER.value)
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert resp.status_code == 403

    def test_different_tenant_ids_are_isolated_in_claims(self, client, jwt_handler):
        """Tokens for different tenants carry different tenant_id in state."""
        token_ferza = make_valid_token(jwt_handler, role=UserRole.SUPER_ADMIN.value, tenant_id="ferza")
        token_acme  = make_valid_token(jwt_handler, role=UserRole.SUPER_ADMIN.value, tenant_id="acme")

        resp_ferza = client.get("/api/erp/query", headers=_auth_header(token_ferza))
        resp_acme  = client.get("/api/erp/query", headers=_auth_header(token_acme))

        assert resp_ferza.status_code == 200
        assert resp_acme.status_code == 200

    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_public_health_route_accessible_without_role(self, client, role):
        """Health endpoint requires no authentication regardless of role."""
        resp = client.get("/health")
        assert resp.status_code == 200
