"""
Use case: EmbedAssetUseCase — Sprint 7 refactor

Pipeline:
  1. Idempotency check — skip if vectors already stored
  2. Load chunks from ChunkStorePort
  3. Embed each chunk via EmbeddingPort
  4. Upsert each chunk's vector into VectorStorePort
  5. Record total vector count in VectorStorePort
"""
from __future__ import annotations

import time

from src.domain.chunk import Chunk
from src.domain.embed_result import EmbedResult
from src.domain.ports.chunk_store_port import ChunkStorePort
from src.domain.ports.embedding_port import EmbeddingPort
from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class AssetAlreadyEmbeddedError(Exception):
    """Raised when vectors already exist for this asset."""


class EmbedAssetUseCase:
    """Load chunks from store, embed per chunk, upsert into vector store.

    Args:
        vector_store:   Tracks which assets are embedded and stores vectors.
        chunk_store:    Provides persisted chunks for the asset.
        embedding_port: Converts chunk text to a float embedding vector.
    """

    def __init__(
        self,
        vector_store: VectorStorePort,
        chunk_store: ChunkStorePort,
        embedding_port: EmbeddingPort,
    ) -> None:
        self._vector_store = vector_store
        self._chunk_store = chunk_store
        self._embedding_port = embedding_port

    def execute(
        self,
        *,
        asset_id: str,
        tenant_id: str,
        chunk_strategy: str,
        task_id: str,
        force: bool = False,
    ) -> EmbedResult:
        """Embed all chunks for ``asset_id`` / ``tenant_id``.

        Args:
            force: embed even if a completion marker already exists. The guard
                exists so a re-delivered Celery message does not redo finished
                work; a reconciliation run wants exactly the opposite, because
                it has already established that the recorded vectors disagree
                with the chunks. Upserts are keyed by chunk_id, so a forced run
                converges on the same records rather than duplicating them.

        Raises:
            AssetAlreadyEmbeddedError: vectors already exist and force is False.
            Any exception from EmbeddingPort propagates — no partial upserts.
        """
        if not force and self._vector_store.has_vectors(asset_id, tenant_id):
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

        chunks: list[Chunk] = self._chunk_store.find_by_asset(asset_id, tenant_id)
        logger.debug(
            "embed_use_case.chunks_loaded",
            asset_id=asset_id,
            chunk_count=len(chunks),
        )

        for chunk in chunks:
            embedding = self._embedding_port.embed(chunk.text)
            self._vector_store.upsert(
                asset_id=asset_id,
                tenant_id=tenant_id,
                embedding=embedding,
                chunk_id=chunk.chunk_id,
                content=chunk.text,
                erp_module=chunk.metadata.get("erp_module"),
            )

        vector_count = len(chunks)
        self._vector_store.save_vectors(asset_id, tenant_id, vector_count)

        duration_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "embed_use_case.success",
            asset_id=asset_id,
            tenant_id=tenant_id,
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
