"""
User Repository — Sprint 3
InMemoryUserRepository for tests and early development.
Sprint 7+ will replace with MongoUserRepository.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from passlib.context import CryptContext

from src.domain.user_role import UserRole

# sha256_crypt: no bcrypt version compatibility issues, suitable for dev/test.
# Production hardening (argon2 / scrypt) is a Sprint 10 task.
_pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


@dataclass
class UserRecord:
    user_id: str
    username: str
    hashed_password: str
    role: str
    tenant_id: str
    reset_token: Optional[str] = None


class UserNotFoundError(Exception):
    pass


class UserAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InMemoryUserRepository:
    """Thread-unsafe in-memory user store for tests and local dev."""

    def __init__(self) -> None:
        self._store: dict[str, UserRecord] = {}  # username → UserRecord

    def create(
        self,
        username: str,
        password: str,
        role: str = UserRole.REPORTING_ANALYST.value,
        tenant_id: str = "default",
    ) -> UserRecord:
        if username in self._store:
            raise UserAlreadyExistsError(f"User '{username}' already exists.")
        record = UserRecord(
            user_id=str(uuid4()),
            username=username,
            hashed_password=_pwd_context.hash(password),
            role=role,
            tenant_id=tenant_id,
        )
        self._store[username] = record
        return record

    def get_by_username(self, username: str) -> UserRecord:
        if username not in self._store:
            raise UserNotFoundError(f"User '{username}' not found.")
        return self._store[username]

    def verify_password(self, username: str, password: str) -> UserRecord:
        try:
            record = self.get_by_username(username)
        except UserNotFoundError:
            raise InvalidCredentialsError("Invalid username or password.")
        if not _pwd_context.verify(password, record.hashed_password):
            raise InvalidCredentialsError("Invalid username or password.")
        return record

    def save_reset_token(self, username: str, reset_token: str) -> None:
        record = self.get_by_username(username)
        record.reset_token = reset_token

    def reset_password(self, reset_token: str, new_password: str) -> UserRecord:
        for record in self._store.values():
            if record.reset_token == reset_token:
                record.hashed_password = _pwd_context.hash(new_password)
                record.reset_token = None
                return record
        raise UserNotFoundError("Invalid or expired reset token.")


__all__ = [
    "InMemoryUserRepository",
    "UserRecord",
    "UserNotFoundError",
    "UserAlreadyExistsError",
    "InvalidCredentialsError",
]
