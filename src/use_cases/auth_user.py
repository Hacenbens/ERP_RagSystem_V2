"""
AuthUseCase — Sprint 3
Orchestrates register, login, and password-reset flows.
Depends on UserRepository and JWTHandler ports (injected via DI).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from src.infrastructure.auth.jwt_handler import JWTHandler
from src.infrastructure.auth.user_repository import (
    InMemoryUserRepository,
    UserRecord,
)


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    token_type: str
    user_id: str
    role: str
    tenant_id: str


@dataclass(frozen=True)
class RegisterResult:
    user_id: str
    username: str
    role: str
    tenant_id: str


@dataclass(frozen=True)
class PasswordResetResult:
    reset_token: str
    message: str


class AuthUseCase:
    """Orchestrates authentication flows.

    Ports:
        user_repository: InMemoryUserRepository (or future MongoUserRepository)
        jwt_handler: JWTHandler
    """

    def __init__(
        self,
        user_repository: InMemoryUserRepository,
        jwt_handler: JWTHandler,
    ) -> None:
        self._repo = user_repository
        self._jwt = jwt_handler

    def register(
        self,
        username: str,
        password: str,
        role: str = "VIEWER",
        tenant_id: str = "default",
    ) -> RegisterResult:
        """Register a new user. Raises UserAlreadyExistsError if username taken."""
        record: UserRecord = self._repo.create(
            username=username,
            password=password,
            role=role,
            tenant_id=tenant_id,
        )
        return RegisterResult(
            user_id=record.user_id,
            username=record.username,
            role=record.role,
            tenant_id=record.tenant_id,
        )

    def login(self, username: str, password: str) -> LoginResult:
        """Authenticate and return a signed JWT. Raises InvalidCredentialsError on failure."""
        record: UserRecord = self._repo.verify_password(username, password)
        token = self._jwt.issue(
            user_id=record.user_id,
            role=record.role,
            tenant_id=record.tenant_id,
        )
        return LoginResult(
            access_token=token,
            token_type="bearer",
            user_id=record.user_id,
            role=record.role,
            tenant_id=record.tenant_id,
        )

    def request_password_reset(self, username: str) -> PasswordResetResult:
        """Generate and store a password reset token for the given username."""
        # Verify user exists (raises UserNotFoundError if not)
        self._repo.get_by_username(username)
        reset_token = secrets.token_urlsafe(32)
        self._repo.save_reset_token(username, reset_token)
        return PasswordResetResult(
            reset_token=reset_token,
            message="Password reset token issued. Use POST /auth/reset-password.",
        )

    def reset_password(self, reset_token: str, new_password: str) -> dict:
        """Reset password using a valid reset token."""
        self._repo.reset_password(reset_token, new_password)
        return {"message": "Password reset successfully."}


__all__ = ["AuthUseCase", "LoginResult", "RegisterResult", "PasswordResetResult"]
