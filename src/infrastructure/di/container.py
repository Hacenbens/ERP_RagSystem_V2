"""
DI Container — Sprint 3
Registers port → implementation bindings and validates completeness at startup.

Usage:
    container = DIContainer()
    container.register("user_repository", MongoUserRepository(db))
    container.validate()           # raises MissingBindingError if any required port is unbound
    repo = container.get("user_repository")

Hard rule (Architecture Mapping): container.validate() MUST be called at startup.
The app must refuse to start if any required port has no binding.
"""
from __future__ import annotations

from typing import Any


class MissingBindingError(RuntimeError):
    """Raised by DIContainer.validate() when a required port has no binding."""


class DIContainer:
    """Simple service-locator style DI container.

    Ports are named string keys.  Implementations are any objects.
    Required ports are declared up-front; validate() checks all are bound.
    """

    # Ports that MUST be bound before the app can start
    REQUIRED_PORTS: tuple[str, ...] = (
        "user_repository",
        "jwt_handler",
        "auth_use_case",
    )

    def __init__(self) -> None:
        self._bindings: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, port: str, implementation: Any) -> None:
        """Bind `implementation` to `port`.  Overwrites any existing binding."""
        self._bindings[port] = implementation

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def get(self, port: str) -> Any:
        """Return the bound implementation for `port`.

        Raises KeyError if the port has no binding.
        """
        if port not in self._bindings:
            raise KeyError(f"No binding registered for port '{port}'.")
        return self._bindings[port]

    # ------------------------------------------------------------------
    # Validation — called at app startup
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Verify all REQUIRED_PORTS have bindings.

        Raises MissingBindingError listing every unbound required port.
        The application must not start if this raises.
        """
        missing = [p for p in self.REQUIRED_PORTS if p not in self._bindings]
        if missing:
            raise MissingBindingError(
                f"DIContainer.validate() failed — unbound required ports: {missing}. "
                "Register all required ports before starting the application."
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def registered_ports(self) -> list[str]:
        """Return the names of all currently bound ports."""
        return list(self._bindings.keys())

    def is_bound(self, port: str) -> bool:
        return port in self._bindings

    def __repr__(self) -> str:
        bound = list(self._bindings.keys())
        missing = [p for p in self.REQUIRED_PORTS if p not in self._bindings]
        return (
            f"DIContainer(bound={bound}, missing_required={missing})"
        )


__all__ = ["DIContainer", "MissingBindingError"]
