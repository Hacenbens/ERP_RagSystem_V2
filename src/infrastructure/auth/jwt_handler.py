"""
JWT Handler — Sprint 3
RS256 token issuance and verification.

In production: load RSA keys from env vars / file paths.
In tests: generate an ephemeral RSA key pair via generate_test_key_pair().
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Token claims schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    role: str
    tenant_id: str
    exp: int
    iat: int
    sub: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TokenExpiredError(Exception):
    """Raised when the JWT has expired."""


class TokenInvalidError(Exception):
    """Raised when the JWT signature or structure is invalid."""


class TokenAlgorithmError(Exception):
    """Raised when the JWT uses an unexpected algorithm."""


# ---------------------------------------------------------------------------
# Key loading helpers
# ---------------------------------------------------------------------------

EXPECTED_ALGORITHM = "RS256"
_DEFAULT_EXPIRY_SECONDS = int(os.environ.get("JWT_EXPIRY_MINUTES", "60")) * 60


def _read_pem(pem_var: str, path_var: str) -> str:
    """Return PEM text from *pem_var*, or from the file named by *path_var*.

    A PEM is multi-line, which is awkward to carry in an environment variable
    and easy to mangle in a shell or a compose file, so a path is accepted as
    the friendlier alternative. The inline variable wins when both are set.
    """
    inline = os.environ.get(pem_var, "")
    if inline.strip():
        return inline
    path = os.environ.get(path_var, "")
    if path.strip():
        return Path(path).read_text()
    return ""


def _load_private_key_from_env() -> Optional[rsa.RSAPrivateKey]:
    pem = _read_pem("JWT_PRIVATE_KEY_PEM", "JWT_PRIVATE_KEY_PATH")
    if not pem:
        return None
    return serialization.load_pem_private_key(pem.encode(), password=None)  # type: ignore[return-value]


def _load_public_key_from_env() -> Optional[rsa.RSAPublicKey]:
    pem = _read_pem("JWT_PUBLIC_KEY_PEM", "JWT_PUBLIC_KEY_PATH")
    if not pem:
        return None
    return serialization.load_pem_public_key(pem.encode())  # type: ignore[return-value]


def generate_test_key_pair() -> tuple[bytes, bytes]:
    """Generate an ephemeral RSA-2048 key pair for use in tests.

    Returns:
        (private_key_pem, public_key_pem) as bytes
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


# ---------------------------------------------------------------------------
# JWTHandler
# ---------------------------------------------------------------------------

class JWTHandler:
    """Issue and verify RS256 JWT tokens.

    Keys are loaded from environment variables JWT_PRIVATE_KEY_PEM and
    JWT_PUBLIC_KEY_PEM.  If those are absent (e.g. in tests), an ephemeral
    RSA key pair is generated automatically.
    """

    def __init__(
        self,
        private_key_pem: Optional[bytes] = None,
        public_key_pem: Optional[bytes] = None,
        expiry_seconds: int = _DEFAULT_EXPIRY_SECONDS,
    ) -> None:
        if private_key_pem and public_key_pem:
            self._private_pem = private_key_pem
            self._public_pem = public_key_pem
        else:
            # Try env vars first, fall back to ephemeral key pair
            env_private = _load_private_key_from_env()
            env_public = _load_public_key_from_env()
            if env_private and env_public:
                self._private_pem = env_private.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
                self._public_pem = env_public.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            else:
                # Every process that reaches this line signs with a different
                # key. Two uvicorn workers reject each other's tokens, and a
                # restart invalidates every session in flight. Fine for tests,
                # never acceptable for a deployment — hence the warning.
                logger.warning(
                    "jwt.ephemeral_keypair — no JWT_PRIVATE_KEY_PEM/"
                    "JWT_PRIVATE_KEY_PATH configured, so this process generated "
                    "its own signing key. Tokens will not validate in any other "
                    "process and will not survive a restart."
                )
                self._private_pem, self._public_pem = generate_test_key_pair()

        self._expiry_seconds = expiry_seconds

    # ------------------------------------------------------------------
    # Issue
    # ------------------------------------------------------------------

    def issue(self, user_id: str, role: str, tenant_id: str) -> str:
        """Issue a signed RS256 JWT for the given user context."""
        now = int(time.time())
        payload = {
            "sub": user_id,
            "user_id": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "iat": now,
            "exp": now + self._expiry_seconds,
        }
        return jwt.encode(payload, self._private_pem, algorithm=EXPECTED_ALGORITHM)

    def issue_expired(self, user_id: str, role: str, tenant_id: str) -> str:
        """Issue a token that is already expired (for testing only)."""
        now = int(time.time()) - 3600  # 1 hour in the past
        payload = {
            "sub": user_id,
            "user_id": user_id,
            "role": role,
            "tenant_id": tenant_id,
            "iat": now - 3600,
            "exp": now,
        }
        return jwt.encode(payload, self._private_pem, algorithm=EXPECTED_ALGORITHM)

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def verify(self, token: str) -> TokenClaims:
        """Verify and decode a JWT.  Returns TokenClaims on success.

        Raises:
            TokenExpiredError: token has expired
            TokenAlgorithmError: token uses an unexpected algorithm
            TokenInvalidError: signature invalid, missing claims, or malformed
        """
        try:
            header = jwt.get_unverified_header(token)
        except jwt.exceptions.DecodeError as exc:
            raise TokenInvalidError(f"Malformed token header: {exc}") from exc

        if header.get("alg") != EXPECTED_ALGORITHM:
            raise TokenAlgorithmError(
                f"Expected algorithm {EXPECTED_ALGORITHM}, got {header.get('alg')}."
            )

        try:
            payload = jwt.decode(
                token,
                self._public_pem,
                algorithms=[EXPECTED_ALGORITHM],
            )
        except jwt.exceptions.ExpiredSignatureError as exc:
            raise TokenExpiredError("Token has expired.") from exc
        except jwt.exceptions.InvalidSignatureError as exc:
            raise TokenInvalidError(f"Invalid token signature: {exc}") from exc
        except jwt.exceptions.DecodeError as exc:
            raise TokenInvalidError(f"Token decode error: {exc}") from exc

        try:
            return TokenClaims(
                user_id=payload["user_id"],
                role=payload["role"],
                tenant_id=payload["tenant_id"],
                exp=payload["exp"],
                iat=payload["iat"],
                sub=payload["sub"],
            )
        except KeyError as exc:
            raise TokenInvalidError(f"Token missing required claim: {exc}") from exc

    @property
    def public_key_pem(self) -> bytes:
        return self._public_pem


__all__ = [
    "JWTHandler",
    "TokenClaims",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenAlgorithmError",
    "generate_test_key_pair",
]
