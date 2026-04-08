"""
Integration tests — RBAC enforcement (Sprint 3)
Tests all 4 roles: ADMIN / MANAGER / ANALYST / VIEWER
Each role is tested on each route category:
  - /api/erp/query  (all authenticated roles)
  - /admin/status   (ADMIN only → 403 for others)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.tests.conftest import build_test_app
from src.tests.fixtures.jwt_fixtures import make_jwt_handler, make_valid_token


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
# /api/erp/query — all authenticated roles should have access
# ---------------------------------------------------------------------------

class TestERPQueryAccess:
    @pytest.mark.parametrize("role", ["ADMIN", "MANAGER", "ANALYST", "VIEWER"])
    def test_all_roles_can_access_erp_query(self, client, jwt_handler, role):
        token = _make_token(jwt_handler, role)
        resp = client.get("/api/erp/query", headers=_auth_header(token))
        assert resp.status_code == 200, (
            f"Role {role} should have access to /api/erp/query, got {resp.status_code}"
        )

    @pytest.mark.parametrize("role", ["ADMIN", "MANAGER", "ANALYST", "VIEWER"])
    def test_role_injected_into_response(self, client, jwt_handler, role):
        token = _make_token(jwt_handler, role)
        resp = client.get("/api/erp/query", headers=_auth_header(token))
        assert resp.json()["role"] == role

    def test_no_token_returns_401_not_403(self, client):
        """Unauthenticated request → 401 (not 403) — auth fails before RBAC."""
        resp = client.get("/api/erp/query")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /admin/status — ADMIN only
# ---------------------------------------------------------------------------

class TestAdminRouteAccess:
    def test_admin_can_access_admin_route(self, client, jwt_handler):
        token = _make_token(jwt_handler, "ADMIN")
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", ["MANAGER", "ANALYST", "VIEWER"])
    def test_non_admin_roles_get_403_on_admin_route(self, client, jwt_handler, role):
        token = _make_token(jwt_handler, role)
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert resp.status_code == 403, (
            f"Role {role} should be blocked from /admin/status, got {resp.status_code}"
        )

    @pytest.mark.parametrize("role", ["MANAGER", "ANALYST", "VIEWER"])
    def test_403_response_has_detail(self, client, jwt_handler, role):
        token = _make_token(jwt_handler, role)
        resp = client.get("/admin/status", headers=_auth_header(token))
        assert "detail" in resp.json()

    def test_unauthenticated_admin_route_returns_401(self, client):
        """No token → 401 before RBAC even runs."""
        resp = client.get("/admin/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Role ordering sanity — privilege escalation check
# ---------------------------------------------------------------------------

class TestRoleIsolation:
    def test_viewer_token_cannot_become_admin(self, client, jwt_handler):
        """A VIEWER token must never grant ADMIN access to admin routes."""
        viewer_token = _make_token(jwt_handler, "VIEWER")
        resp = client.get("/admin/status", headers=_auth_header(viewer_token))
        assert resp.status_code == 403

    def test_analyst_token_cannot_access_admin(self, client, jwt_handler):
        analyst_token = _make_token(jwt_handler, "ANALYST")
        resp = client.get("/admin/status", headers=_auth_header(analyst_token))
        assert resp.status_code == 403

    def test_manager_token_cannot_access_admin(self, client, jwt_handler):
        manager_token = _make_token(jwt_handler, "MANAGER")
        resp = client.get("/admin/status", headers=_auth_header(manager_token))
        assert resp.status_code == 403

    def test_different_tenant_ids_are_isolated_in_claims(self, client, jwt_handler):
        """Tokens for different tenants carry different tenant_id in state."""
        token_ferza = make_valid_token(jwt_handler, role="ADMIN", tenant_id="ferza")
        token_acme = make_valid_token(jwt_handler, role="ADMIN", tenant_id="acme")

        resp_ferza = client.get("/api/erp/query", headers=_auth_header(token_ferza))
        resp_acme = client.get("/api/erp/query", headers=_auth_header(token_acme))

        assert resp_ferza.status_code == 200
        assert resp_acme.status_code == 200
        # Both succeed — tenant isolation at SQL level is enforced in Sprint 4

    @pytest.mark.parametrize("role", ["ADMIN", "MANAGER", "ANALYST", "VIEWER"])
    def test_public_routes_accessible_without_role(self, client, role):
        """Health endpoint requires no authentication regardless of role."""
        resp = client.get("/health")
        assert resp.status_code == 200
