"""
JWT test fixtures — Sprint 3
Generates ephemeral RSA key pairs and tokens for tests.
Never hits a real IdP — all crypto is local.
"""
from __future__ import annotations

import time
import jwt

from src.infrastructure.auth.jwt_handler import JWTHandler, generate_test_key_pair


def make_jwt_handler() -> JWTHandler:
    """Return a JWTHandler with a fresh ephemeral RSA key pair."""
    private_pem, public_pem = generate_test_key_pair()
    return JWTHandler(private_key_pem=private_pem, public_key_pem=public_pem)


def make_valid_token(
    handler: JWTHandler,
    user_id: str = "test-user",
    role: str = "ADMIN",
    tenant_id: str = "test-tenant",
) -> str:
    return handler.issue(user_id=user_id, role=role, tenant_id=tenant_id)


def make_expired_token(handler: JWTHandler) -> str:
    return handler.issue_expired(
        user_id="test-user", role="ADMIN", tenant_id="test-tenant"
    )


def make_tampered_token(handler: JWTHandler) -> str:
    """Return a valid token with its signature replaced by garbage."""
    token = make_valid_token(handler)
    header_b64, payload_b64, _ = token.split(".")
    return f"{header_b64}.{payload_b64}.invalidsignature"


def make_wrong_algorithm_token(handler: JWTHandler, secret: str = "wrong-secret") -> str:
    """Return a HS256 token (wrong algorithm for our RS256 validator)."""
    payload = {
        "sub": "test-user",
        "user_id": "test-user",
        "role": "ADMIN",
        "tenant_id": "test-tenant",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


__all__ = [
    "make_jwt_handler",
    "make_valid_token",
    "make_expired_token",
    "make_tampered_token",
    "make_wrong_algorithm_token",
]
