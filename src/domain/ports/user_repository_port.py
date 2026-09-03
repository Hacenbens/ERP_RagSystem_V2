"""
Port: UserRepositoryPort

Abstract interface for user account storage.
Infrastructure implementations live in src/infrastructure/auth/user_repository.py.

AuthUseCase type-hinted the concrete InMemoryUserRepository, so the use case
layer depended on an infrastructure class that loses every account on restart
and holds a different table in each process. This port is what lets the DI
container swap in a durable repository without the use case knowing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.user_record import UserRecord
from src.domain.user_role import UserRole


class UserRepositoryPort(ABC):
    """Create, look up and authenticate user accounts."""

    @abstractmethod
    def create(
        self,
        username: str,
        password: str,
        role: str = UserRole.REPORTING_ANALYST.value,
        tenant_id: str = "default",
    ) -> UserRecord:
        """Store a new user with a hashed password.

        Raises:
            UserAlreadyExistsError: the username is taken.
        """

    @abstractmethod
    def get_by_username(self, username: str) -> UserRecord:
        """Return the stored user.

        Raises:
            UserNotFoundError: no such user.
        """

    @abstractmethod
    def verify_password(self, username: str, password: str) -> UserRecord:
        """Return the user when the password matches.

        Raises:
            InvalidCredentialsError: unknown user or wrong password. The same
                error for both, so the caller cannot enumerate usernames.
        """

    @abstractmethod
    def save_reset_token(self, username: str, reset_token: str) -> None:
        """Attach a password-reset token to the user."""

    @abstractmethod
    def reset_password(self, reset_token: str, new_password: str) -> UserRecord:
        """Set a new password for whoever holds *reset_token* and clear it.

        Raises:
            UserNotFoundError: the token matches no user.
        """


__all__ = ["UserRepositoryPort"]
