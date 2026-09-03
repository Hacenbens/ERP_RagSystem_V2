"""
UserRecord — a stored user account.

Pure domain entity, no infrastructure dependencies. It lived in
src/infrastructure/auth/user_repository.py, which meant UserRepositoryPort
could not name the type it returns without the domain layer importing from
infrastructure — so the port returned ``object`` and every caller had to
re-assert the type.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class UserRecord:
    """One user account as stored by any UserRepositoryPort implementation."""

    user_id: str
    username: str
    hashed_password: str
    role: str
    tenant_id: str
    reset_token: Optional[str] = None


__all__ = ["UserRecord"]
