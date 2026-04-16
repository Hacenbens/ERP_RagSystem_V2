"""
DI Factory — Sprint 3
Wires all concrete implementations into the DIContainer.

Call `build_container()` once at app startup (e.g. in main.py lifespan).
The returned container has been validated — it will raise on missing bindings
before returning.
"""
from __future__ import annotations

from src.infrastructure.di.container import DIContainer


def build_container() -> DIContainer:
    """Create and validate the DI container with all production bindings.

    Raises MissingBindingError at startup if a required port has no implementation.
    """
    container = DIContainer()

    # --- Auth -----------------------------------------------------------
    from src.infrastructure.auth.jwt_handler import JWTHandler
    from src.infrastructure.auth.user_repository import InMemoryUserRepository
    from src.use_cases.auth_user import AuthUseCase

    jwt_handler = JWTHandler()
    user_repo = InMemoryUserRepository()
    auth_use_case = AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler)

    container.register("jwt_handler", jwt_handler)
    container.register("user_repository", user_repo)
    container.register("auth_use_case", auth_use_case)

    # Validate before returning — app must not start with unbound ports
    container.validate()
    return container


__all__ = ["build_container"]
