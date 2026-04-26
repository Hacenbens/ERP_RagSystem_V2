"""
Use case: IngestAssetUseCase — Sprint 7 refactor

Pipeline:
  1. Idempotency check — skip if already processed
  2. Load raw bytes via AssetStoragePort
  3. Chunk via injected callable -> list[Chunk]
  4. Persist chunks via ChunkStorePort
  5. Mark asset processed in idempotency store
"""
from __future__ import annotations

import time
from typing import Callable

from src.domain.chunk import Chunk
from src.domain.ingest import IngestResult
from src.domain.ports.asset_storage_port import AssetStoragePort
from src.domain.ports.chunk_store_port import ChunkStorePort
from src.domain.ports.idempotency_store import IdempotencyStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_ChunkerProtocol = Callable[[bytes, str], list[Chunk]]


class AssetAlreadyProcessedError(Exception):
    """Raised when idempotency check finds the asset already ingested."""


class IngestAssetUseCase:
    """Chunk and store one document asset.

    Args:
        idempotency_store: Tracks which (asset_id, tenant_id) pairs are processed.
        asset_storage:     Loads raw file bytes by tenant + storage key.
        chunk_store:       Persists the resulting chunks.
        chunker:           ``(content: bytes, strategy: str) -> list[Chunk]``
    """

    def __init__(
        self,
        idempotency_store: IdempotencyStorePort,
        asset_storage: AssetStoragePort,
        chunk_store: ChunkStorePort,
        chunker: _ChunkerProtocol,
    ) -> None:
        self._idempotency = idempotency_store
        self._asset_storage = asset_storage
        self._chunk_store = chunk_store
        self._chunker = chunker

    def execute(
        self,
        *,
        asset_id: str,
        tenant_id: str,
        chunk_strategy: str,
        task_id: str,
    ) -> IngestResult:
        """Run the ingestion pipeline.

        Raises:
            AssetAlreadyProcessedError: asset already ingested.
            FileNotFoundError: storage key not found — propagates without touching chunk_store.
            Any exception from chunker propagates without marking processed.
        """
        if self._idempotency.is_processed(asset_id, tenant_id):
            logger.info(
                "ingest_use_case.skip_duplicate",
                asset_id=asset_id,
                tenant_id=tenant_id,
                task_id=task_id,
            )
            raise AssetAlreadyProcessedError(
                f"Asset {asset_id!r} for tenant {tenant_id!r} already processed."
            )

        logger.info(
            "ingest_use_case.start",
            asset_id=asset_id,
            tenant_id=tenant_id,
            chunk_strategy=chunk_strategy,
            task_id=task_id,
        )

        t0 = time.perf_counter()

        # Stage 1 — load bytes (raises FileNotFoundError if missing)
        content: bytes = self._asset_storage.read_bytes(tenant_id, asset_id)

        # Stage 2 — chunk (raises on failure; chunk_store never touched)
        chunks: list[Chunk] = self._chunker(content, chunk_strategy)

        # Stage 3 — persist chunks
        self._chunk_store.save_chunks(asset_id, tenant_id, chunks)

        # Stage 4 — mark processed only after successful persistence
        self._idempotency.mark_processed(asset_id, tenant_id)

        duration_ms = (time.perf_counter() - t0) * 1000
        chunk_count = len(chunks)

        logger.info(
            "ingest_use_case.success",
            asset_id=asset_id,
            tenant_id=tenant_id,
            chunk_count=chunk_count,
            duration_ms=round(duration_ms, 2),
            task_id=task_id,
        )

        return IngestResult(
            asset_id=asset_id,
            tenant_id=tenant_id,
            chunk_count=chunk_count,
            chunk_strategy=chunk_strategy,
            duration_ms=round(duration_ms, 2),
            task_id=task_id,
        )


__all__ = ["IngestAssetUseCase", "AssetAlreadyProcessedError"]
