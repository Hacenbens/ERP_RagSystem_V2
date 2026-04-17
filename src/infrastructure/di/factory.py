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


def build_worker_container() -> DIContainer:
    """Create and validate a DI container for the Celery worker process.

    Wires all worker-specific dependencies (dead-letter repo, idempotency
    store, ingest use case) in addition to the shared auth bindings.

    Raises MissingBindingError at startup if a required worker port is unbound.

    The choice between in-memory and MongoDB implementations is driven by the
    ``MONGODB_URI`` environment variable — present in production, absent in CI.
    """
    import os

    container = DIContainer()

    # --- Auth (shared with API process) ----------------------------------
    from src.infrastructure.auth.jwt_handler import JWTHandler
    from src.infrastructure.auth.user_repository import InMemoryUserRepository
    from src.use_cases.auth_user import AuthUseCase

    jwt_handler = JWTHandler()
    user_repo = InMemoryUserRepository()
    auth_use_case = AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler)

    container.register("jwt_handler", jwt_handler)
    container.register("user_repository", user_repo)
    container.register("auth_use_case", auth_use_case)

    # --- Worker dependencies ---------------------------------------------
    from src.infrastructure.workers.dead_letter_repository import (
        InMemoryDeadLetterRepository,
        MongoDeadLetterRepository,
    )
    from src.infrastructure.workers.idempotency_store import (
        InMemoryIdempotencyStore,
        MongoIdempotencyStore,
    )
    from src.use_cases.tasks.ingest_asset_use_case import IngestAssetUseCase

    mongo_uri = os.environ.get("MONGODB_URI", "")

    dead_letter_repo: InMemoryDeadLetterRepository | MongoDeadLetterRepository
    idempotency_store: InMemoryIdempotencyStore | MongoIdempotencyStore

    if mongo_uri:
        import pymongo  # type: ignore
        client = pymongo.MongoClient(mongo_uri)
        dead_letter_repo = MongoDeadLetterRepository(
            client["erp_rag"]["failed_tasks"]
        )
        idempotency_store = MongoIdempotencyStore(
            client["erp_rag"]["processed_assets"]
        )
    else:
        dead_letter_repo = InMemoryDeadLetterRepository()
        idempotency_store = InMemoryIdempotencyStore()

    # Chunker is a stub until Sprint 6 Task 3 wires ChunkerFactory
    def _stub_chunker(asset_id: str, tenant_id: str, chunk_strategy: str) -> int:
        raise NotImplementedError(
            "ChunkerFactory not yet wired — implement in Sprint 6 Task 3."
        )

    ingest_use_case = IngestAssetUseCase(
        idempotency_store=idempotency_store,
        chunker=_stub_chunker,
    )

    container.register("dead_letter_repository", dead_letter_repo)
    container.register("idempotency_store", idempotency_store)
    container.register("ingest_use_case", ingest_use_case)

    # Validate worker ports before returning
    container.validate_worker()
    return container


# ---------------------------------------------------------------------------
# Worker container singleton — one instance per worker process
# ---------------------------------------------------------------------------

_worker_container: DIContainer | None = None


def get_worker_container() -> DIContainer:
    """Return the worker DI container, building it on first call.

    Lazy singleton — safe to import at module level in task files because the
    container is only constructed when the first task runs, not at import time.
    """
    global _worker_container
    if _worker_container is None:
        _worker_container = build_worker_container()
    return _worker_container


__all__ = ["build_container", "build_worker_container", "get_worker_container"]
