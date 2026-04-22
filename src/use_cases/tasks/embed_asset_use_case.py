"""
Use case: EmbedAssetUseCase

Orchestrates the vector embedding pipeline for a single asset:
  1. Idempotency check — skip if vectors already exist in the store
  2. Chunk the asset (injected callable) → list[Chunk], each with .text + .metadata
  3. Embed every chunk individually with its metadata (injected callable)
  4. Record the total vector count in the vector store on success

Design rule: embedding operates per-chunk, not per-asset.
Each Chunk becomes one independent retrieval unit in the vector store,
carrying its section/article/table metadata for context-aware retrieval.

This class contains only business logic.
It has no knowledge of Celery, retries, dead-letter queues, or HTTP.
"""
from __future__ import annotations

import time
from typing import Callable

from src.domain.chunk import Chunk
from src.domain.embed_result import EmbedResult
from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# (asset_id, tenant_id, chunk_strategy) → list[Chunk]
_ChunkerProtocol = Callable[[str, str, str], list[Chunk]]

# (chunks, asset_id, tenant_id) → int  (number of vectors stored)
_EmbedderProtocol = Callable[[list[Chunk], str, str], int]


class AssetAlreadyEmbeddedError(Exception):
    """Raised when the idempotency check finds vectors already stored."""


class EmbedAssetUseCase:
    """Chunk then embed one document asset into the vector store.

    Args:
        vector_store: Tracks which assets have been embedded and their
                      vector counts (idempotency guard).
        chunker:      ``(asset_id, tenant_id, strategy) -> list[Chunk]``
                      Splits the asset into chunks; each Chunk carries
                      .text (to embed) and .metadata (to store alongside
                      the vector for context-aware retrieval).
        embedder:     ``(chunks, asset_id, tenant_id) -> int``
                      Embeds each chunk's .text, attaches its .metadata
                      to the stored vector, and returns the total count of
                      vectors written.  Injected so the use case stays
                      testable without a real embedding model.
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        chunker: _ChunkerProtocol,
        embedder: _EmbedderProtocol,
    ) -> None:
        self._vector_store = vector_store
        self._chunker = chunker
        self._embedder = embedder

    def execute(
        self,
        *,
        asset_id: str,
        tenant_id: str,
        chunk_strategy: str,
        task_id: str,
    ) -> EmbedResult:
        """Run the chunk → embed pipeline.

        Args:
            asset_id:       ID of the asset to embed.
            tenant_id:      Owning tenant (for isolation).
            chunk_strategy: Strategy name forwarded to the chunker.
            task_id:        Celery task ID for traceability.

        Returns:
            EmbedResult on success.

        Raises:
            AssetAlreadyEmbeddedError: if vectors already exist for this asset.
            Any exception from chunker or embedder propagates — the Celery
            task layer decides whether to retry.
        """
        if self._vector_store.has_vectors(asset_id, tenant_id):
            logger.info(
                "embed_use_case.skip_duplicate",
                asset_id=asset_id,
                tenant_id=tenant_id,
                task_id=task_id,
            )
            raise AssetAlreadyEmbeddedError(
                f"Asset {asset_id!r} for tenant {tenant_id!r} already embedded."
            )

        logger.info(
            "embed_use_case.start",
            asset_id=asset_id,
            tenant_id=tenant_id,
            chunk_strategy=chunk_strategy,
            task_id=task_id,
        )

        t0 = time.perf_counter()

        # Stage 1 — chunk the asset
        chunks: list[Chunk] = self._chunker(asset_id, tenant_id, chunk_strategy)
        logger.debug(
            "embed_use_case.chunked",
            asset_id=asset_id,
            chunk_count=len(chunks),
            task_id=task_id,
        )

        # Stage 2 — embed each chunk with its metadata
        vector_count: int = self._embedder(chunks, asset_id, tenant_id)

        duration_ms = (time.perf_counter() - t0) * 1000

        self._vector_store.save_vectors(asset_id, tenant_id, vector_count)

        logger.info(
            "embed_use_case.success",
            asset_id=asset_id,
            tenant_id=tenant_id,
            chunk_count=len(chunks),
            vector_count=vector_count,
            duration_ms=round(duration_ms, 2),
            task_id=task_id,
        )

        return EmbedResult(
            asset_id=asset_id,
            tenant_id=tenant_id,
            vector_count=vector_count,
            chunk_strategy=chunk_strategy,
            duration_ms=round(duration_ms, 2),
            task_id=task_id,
        )


__all__ = ["EmbedAssetUseCase", "AssetAlreadyEmbeddedError"]
