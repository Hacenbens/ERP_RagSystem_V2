"""
DI Factory — Sprint 3 / Sprint 6
Wires all concrete implementations into the DIContainer.

Call `build_container()` once at app startup (e.g. in main.py lifespan).
The returned container has been validated — it will raise on missing bindings
before returning.
"""
from __future__ import annotations

import os

from src.domain.chunk import Chunk
from src.domain.chunk_strategy import ChunkStrategy
from src.infrastructure.auth.jwt_handler import JWTHandler
from src.infrastructure.auth.user_repository import InMemoryUserRepository
from src.infrastructure.di.container import DIContainer
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.infrastructure.workers.chunkers.chunker_factory import ChunkerFactory
from src.infrastructure.workers.dead_letter_repository import (
    InMemoryDeadLetterRepository,
    MongoDeadLetterRepository,
)
from src.infrastructure.workers.idempotency_store import (
    InMemoryIdempotencyStore,
    MongoIdempotencyStore,
)
from src.use_cases.auth_user import AuthUseCase
from src.use_cases.tasks.embed_asset_use_case import EmbedAssetUseCase
from src.use_cases.tasks.ingest_asset_use_case import IngestAssetUseCase


def build_container() -> DIContainer:
    """Create and validate the DI container with all production bindings.

    Raises MissingBindingError at startup if a required port has no implementation.
    """
    container = DIContainer()

    # --- Auth -----------------------------------------------------------
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
    store, ingest use case, embed use case) in addition to the shared auth
    bindings.

    Raises MissingBindingError at startup if a required worker port is unbound.

    The choice between in-memory and MongoDB implementations is driven by the
    ``MONGODB_URI`` environment variable — present in production, absent in CI.
    """
    container = DIContainer()

    # --- Auth (shared with API process) ----------------------------------
    jwt_handler = JWTHandler()
    user_repo = InMemoryUserRepository()
    auth_use_case = AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler)

    container.register("jwt_handler", jwt_handler)
    container.register("user_repository", user_repo)
    container.register("auth_use_case", auth_use_case)

    # --- Worker dependencies ---------------------------------------------
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
        from src.infrastructure.vector_store.mongo_vector_store import MongoVectorStore
        vector_store: InMemoryVectorStore | MongoVectorStore = MongoVectorStore(
            client["erp_rag"]["embedded_assets"]
        )
    else:
        dead_letter_repo = InMemoryDeadLetterRepository()
        idempotency_store = InMemoryIdempotencyStore()
        vector_store = InMemoryVectorStore()

    _chunker_factory = ChunkerFactory()

    def _ingest_chunker(asset_id: str, tenant_id: str, chunk_strategy: str) -> int:
        """Resolve strategy → chunker → chunk count stub.

        Full content-fetch from MinIO/MongoDB is wired in Sprint 7.
        For now the factory validates the strategy and returns a
        deterministic chunk count so the task pipeline is testable.
        """
        strategy = ChunkStrategy(chunk_strategy)
        chunker = _chunker_factory.get_chunker(strategy)
        placeholder = f"asset:{asset_id} tenant:{tenant_id} strategy:{chunk_strategy}"
        chunks = chunker.chunk(placeholder)
        return max(len(chunks), 1)

    def _embed_chunker(asset_id: str, tenant_id: str, chunk_strategy: str) -> list[Chunk]:
        """Resolve strategy → chunker → list[Chunk] stub.

        Returns real Chunk objects with text + metadata so the embedder
        can store per-chunk vectors.  Content fetch is a placeholder until
        Sprint 7 wires the real document store.
        """
        strategy = ChunkStrategy(chunk_strategy)
        chunker = _chunker_factory.get_chunker(strategy)
        placeholder = f"asset:{asset_id} tenant:{tenant_id} strategy:{chunk_strategy}"
        chunks = chunker.chunk(placeholder)
        return chunks if chunks else [
            Chunk(text=placeholder, metadata={"asset_id": asset_id, "tenant_id": tenant_id})
        ]

    def _embed_embedder(chunks: list[Chunk], asset_id: str, tenant_id: str) -> int:
        """Stub embedder — counts vectors without calling a real model.

        Sprint 7 will replace this with a real embedding model call that
        stores float vectors in Milvus alongside each chunk's metadata.
        """
        return len(chunks)

    ingest_use_case = IngestAssetUseCase(
        idempotency_store=idempotency_store,
        chunker=_ingest_chunker,
    )

    embed_use_case = EmbedAssetUseCase(
        vector_store=vector_store,
        chunker=_embed_chunker,
        embedder=_embed_embedder,
    )

    container.register("dead_letter_repository", dead_letter_repo)
    container.register("idempotency_store", idempotency_store)
    container.register("ingest_use_case", ingest_use_case)
    container.register("vector_store", vector_store)
    container.register("embed_use_case", embed_use_case)

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
