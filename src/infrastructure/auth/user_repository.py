"""
User repositories — Sprint 3, made durable in Sprint 11.

InMemoryUserRepository is for tests and local runs; MongoUserRepository is the
production store. Both implement UserRepositoryPort, so the DI container picks
one from MONGODB_URI without the use case layer knowing which.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from passlib.context import CryptContext

from src.domain.ports.user_repository_port import UserRepositoryPort
from src.domain.user_record import UserRecord
from src.domain.user_role import UserRole
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# scrypt is memory-hard, so it resists GPU cracking in a way sha256_crypt does
# not. It needs no extra package: passlib delegates to hashlib.scrypt.
#
# sha256_crypt stays registered as deprecated so accounts created before this
# change still log in. passlib then reports needs_update() on those hashes and
# the repositories transparently re-hash on the next successful login, so the
# old digests drain away without a migration or a forced password reset.
_pwd_context = CryptContext(
    schemes=["scrypt", "sha256_crypt"],
    deprecated=["sha256_crypt"],
)


class UserNotFoundError(Exception):
    pass


class UserAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InMemoryUserRepository(UserRepositoryPort):
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
            # Same error as a wrong password, so the caller cannot enumerate
            # usernames by comparing responses.
            raise InvalidCredentialsError("Invalid username or password.")
        if not _pwd_context.verify(password, record.hashed_password):
            raise InvalidCredentialsError("Invalid username or password.")
        if _pwd_context.needs_update(record.hashed_password):
            record.hashed_password = _pwd_context.hash(password)
            logger.info("user_repository.password_rehashed", username=username)
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


class MongoUserRepository(UserRepositoryPort):
    """MongoDB-backed user store.

    Accounts survive a restart and are shared across processes, which
    InMemoryUserRepository cannot do: it holds a separate table per process, so
    a user registered against one uvicorn worker did not exist for the next
    request served by another.

    Args:
        collection: a pymongo collection. A unique index on ``username`` is
            created on construction, so a duplicate registration racing between
            two processes fails at the database rather than silently producing
            two accounts.
    """

    def __init__(self, collection: Any) -> None:
        self._col = collection
        self._col.create_index("username", unique=True)

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _to_record(doc: dict[str, Any]) -> UserRecord:
        return UserRecord(
            user_id=doc["user_id"],
            username=doc["username"],
            hashed_password=doc["hashed_password"],
            role=doc["role"],
            tenant_id=doc["tenant_id"],
            reset_token=doc.get("reset_token"),
        )

    # ------------------------------------------------------------------
    # UserRepositoryPort
    # ------------------------------------------------------------------

    def create(
        self,
        username: str,
        password: str,
        role: str = UserRole.REPORTING_ANALYST.value,
        tenant_id: str = "default",
    ) -> UserRecord:
        """Insert a new user, or raise if the username is taken."""
        from pymongo.errors import DuplicateKeyError  # type: ignore

        record = UserRecord(
            user_id=str(uuid4()),
            username=username,
            hashed_password=_pwd_context.hash(password),
            role=role,
            tenant_id=tenant_id,
        )
        try:
            self._col.insert_one(record.__dict__.copy())
        except DuplicateKeyError as exc:
            raise UserAlreadyExistsError(f"User {username!r} already exists.") from exc
        return record

    def get_by_username(self, username: str) -> UserRecord:
        """Return the stored user, or raise UserNotFoundError."""
        doc = self._col.find_one({"username": username})
        if doc is None:
            raise UserNotFoundError(f"User {username!r} not found.")
        return self._to_record(doc)

    def verify_password(self, username: str, password: str) -> UserRecord:
        """Return the user when the password matches, re-hashing stale digests."""
        try:
            record = self.get_by_username(username)
        except UserNotFoundError:
            raise InvalidCredentialsError("Invalid username or password.")
        if not _pwd_context.verify(password, record.hashed_password):
            raise InvalidCredentialsError("Invalid username or password.")
        if _pwd_context.needs_update(record.hashed_password):
            new_hash = _pwd_context.hash(password)
            self._col.update_one(
                {"username": username}, {"$set": {"hashed_password": new_hash}}
            )
            record.hashed_password = new_hash
            logger.info("user_repository.password_rehashed", username=username)
        return record

    def save_reset_token(self, username: str, reset_token: str) -> None:
        """Attach a reset token, or raise if the user does not exist."""
        result = self._col.update_one(
            {"username": username}, {"$set": {"reset_token": reset_token}}
        )
        if result.matched_count == 0:
            raise UserNotFoundError(f"User {username!r} not found.")

    def reset_password(self, reset_token: str, new_password: str) -> UserRecord:
        """Set a new password for the token holder and clear the token."""
        doc = self._col.find_one({"reset_token": reset_token})
        if doc is None:
            raise UserNotFoundError("Invalid or expired reset token.")
        self._col.update_one(
            {"user_id": doc["user_id"]},
            {"$set": {"hashed_password": _pwd_context.hash(new_password),
                      "reset_token": None}},
        )
        return self.get_by_username(doc["username"])


__all__ = [
    "InMemoryUserRepository",
    "MongoUserRepository",
    "UserRecord",
    "UserNotFoundError",
    "UserAlreadyExistsError",
    "InvalidCredentialsError",
]
