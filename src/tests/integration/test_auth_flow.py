"""
Integration tests — Full Auth Flow (Sprint 3)
Covers: register → login → use token → all 401 failure cases
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.tests.conftest import build_test_app
from src.tests.fixtures.jwt_fixtures import (
    make_expired_token,
    make_jwt_handler,
    make_tampered_token,
    make_wrong_algorithm_token,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def jwt_handler():
    return make_jwt_handler()


@pytest.fixture()
def client(jwt_handler):
    app, _ = build_test_app(jwt_handler=jwt_handler)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Happy path: register → login → use token
# ---------------------------------------------------------------------------

class TestRegisterAndLogin:
    def test_register_new_user_returns_201(self, client):
        resp = client.post("/auth/register", json={
            "username": "alice",
            "password": "securepass1",
            "role": "ANALYST",
            "tenant_id": "ferza",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "alice"
        assert data["role"] == "ANALYST"
        assert data["tenant_id"] == "ferza"
        assert "user_id" in data

    def test_register_duplicate_username_returns_409(self, client):
        payload = {"username": "bob", "password": "pass12345", "role": "VIEWER", "tenant_id": "t1"}
        client.post("/auth/register", json=payload)
        resp = client.post("/auth/register", json=payload)
        assert resp.status_code == 409

    def test_login_returns_access_token(self, client):
        client.post("/auth/register", json={
            "username": "charlie", "password": "pass12345", "role": "MANAGER", "tenant_id": "acme"
        })
        resp = client.post("/auth/login", json={"username": "charlie", "password": "pass12345"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "MANAGER"
        assert data["tenant_id"] == "acme"

    def test_login_with_wrong_password_returns_401(self, client):
        client.post("/auth/register", json={
            "username": "dana", "password": "correct_pass", "role": "VIEWER", "tenant_id": "t1"
        })
        resp = client.post("/auth/login", json={"username": "dana", "password": "wrong_pass"})
        assert resp.status_code == 401

    def test_login_unknown_user_returns_401(self, client):
        resp = client.post("/auth/login", json={"username": "nobody", "password": "anypass"})
        assert resp.status_code == 401

    def test_full_flow_register_login_use_token(self, client):
        """Happy path: register → login → GET /api/erp/query with JWT → 200."""
        # Register
        client.post("/auth/register", json={
            "username": "eve", "password": "pass12345", "role": "ADMIN", "tenant_id": "ferza"
        })
        # Login
        login_resp = client.post("/auth/login", json={"username": "eve", "password": "pass12345"})
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        # Use token on protected endpoint
        resp = client.get(
            "/api/erp/query",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "ok"
        assert data["role"] == "ADMIN"


# ---------------------------------------------------------------------------
# Auth failure cases — all must return 401
# ---------------------------------------------------------------------------

class TestAuthFailureCases:
    def test_missing_authorization_header_returns_401(self, client):
        resp = client.get("/api/erp/query")
        assert resp.status_code == 401
        assert "detail" in resp.json()

    def test_malformed_bearer_header_returns_401(self, client):
        resp = client.get("/api/erp/query", headers={"Authorization": "NotBearer token"})
        assert resp.status_code == 401

    def test_empty_bearer_token_returns_401(self, client):
        resp = client.get("/api/erp/query", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client, jwt_handler):
        expired = make_expired_token(jwt_handler)
        resp = client.get("/api/erp/query", headers={"Authorization": f"Bearer {expired}"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_tampered_token_returns_401(self, client, jwt_handler):
        tampered = make_tampered_token(jwt_handler)
        resp = client.get("/api/erp/query", headers={"Authorization": f"Bearer {tampered}"})
        assert resp.status_code == 401

    def test_wrong_algorithm_token_returns_401(self, client, jwt_handler):
        hs256_token = make_wrong_algorithm_token(jwt_handler)
        resp = client.get("/api/erp/query", headers={"Authorization": f"Bearer {hs256_token}"})
        assert resp.status_code == 401

    def test_completely_random_string_returns_401(self, client):
        resp = client.get("/api/erp/query", headers={"Authorization": "Bearer notajwtatall"})
        assert resp.status_code == 401

    def test_401_response_has_detail_field(self, client):
        resp = client.get("/api/erp/query")
        assert "detail" in resp.json()

    def test_public_paths_require_no_token(self, client):
        """Public paths must be accessible without any Authorization header."""
        assert client.get("/health").status_code == 200
        assert client.post("/auth/login", json={"username": "x", "password": "y"}).status_code in (200, 401)
        assert client.post("/auth/register", json={
            "username": "pub_test", "password": "pass12345", "role": "VIEWER", "tenant_id": "t"
        }).status_code == 201


# ---------------------------------------------------------------------------
# Password reset flow
# ---------------------------------------------------------------------------

class TestPasswordResetFlow:
    def test_request_reset_token_for_existing_user(self, client):
        client.post("/auth/register", json={
            "username": "frank", "password": "oldpass1", "role": "VIEWER", "tenant_id": "t"
        })
        resp = client.post("/auth/request-password-reset", json={"username": "frank"})
        assert resp.status_code == 200
        assert "reset_token" in resp.json()

    def test_request_reset_for_unknown_user_is_safe(self, client):
        """Must not reveal whether username exists."""
        resp = client.post("/auth/request-password-reset", json={"username": "unknown_user_xyz"})
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_reset_password_with_valid_token(self, client):
        client.post("/auth/register", json={
            "username": "grace", "password": "oldpass1", "role": "VIEWER", "tenant_id": "t"
        })
        reset_resp = client.post("/auth/request-password-reset", json={"username": "grace"})
        reset_token = reset_resp.json()["reset_token"]

        resp = client.post("/auth/reset-password", json={
            "reset_token": reset_token,
            "new_password": "newpass123",
        })
        assert resp.status_code == 200

        # Login with new password should succeed
        login_resp = client.post("/auth/login", json={"username": "grace", "password": "newpass123"})
        assert login_resp.status_code == 200

    def test_reset_password_with_invalid_token_returns_400(self, client):
        resp = client.post("/auth/reset-password", json={
            "reset_token": "bad-token",
            "new_password": "newpass123",
        })
        assert resp.status_code == 400

    def test_old_password_rejected_after_reset(self, client):
        client.post("/auth/register", json={
            "username": "henry", "password": "oldpass1", "role": "VIEWER", "tenant_id": "t"
        })
        reset_resp = client.post("/auth/request-password-reset", json={"username": "henry"})
        reset_token = reset_resp.json()["reset_token"]
        client.post("/auth/reset-password", json={
            "reset_token": reset_token, "new_password": "newpass123"
        })
        login_resp = client.post("/auth/login", json={"username": "henry", "password": "oldpass1"})
        assert login_resp.status_code == 401
