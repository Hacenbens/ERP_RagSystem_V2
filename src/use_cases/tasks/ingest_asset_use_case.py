"""
Use case: IngestAssetUseCase

Orchestrates the document ingestion pipeline for a single asset:
  1. Idempotency check — skip if already processed
  2. Delegate to the chunker (injected dependency)
  3. Mark the asset as processed on success

This class contains only business logic.
It has no knowledge of Celery, retries, dead-letter queues, or HTTP.
Those concerns belong to the Celery task layer (src/workers/tasks/).
"""
from __future__ import annotations

import time

from src.domain.ingest import IngestResult
from src.domain.ports.idempotency_store import IdempotencyStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class AssetAlreadyProcessedError(Exception):
    """Raised when idempotency check finds the asset already ingested."""


class IngestAssetUseCase:
    """Chunk and store one document asset.

    Args:
        idempotency_store: Port implementation that tracks processed assets.
        chunker:           Callable ``(asset_id, tenant_id, strategy) -> int``
                           that performs the actual chunk-and-store work and
                           returns the chunk count produced.
                           Injected so the use case stays testable without a
                           real chunker — tests pass a lambda or Mock.
    """

    def __init__(
        self,
        idempotency_store: IdempotencyStorePort,
        chunker: _ChunkerProtocol,
    ) -> None:
        self._idempotency = idempotency_store
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

        Args:
            asset_id:       ID of the asset to ingest.
            tenant_id:      Owning tenant (for isolation).
            chunk_strategy: Strategy name passed to the chunker.
            task_id:        Celery task ID for traceability.

        Returns:
            IngestResult on success.

        Raises:
            AssetAlreadyProcessedError: if this asset was already ingested.
            Any exception raised by the chunker propagates up — the Celery
            task layer decides whether to retry.
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
        chunk_count: int = self._chunker(asset_id, tenant_id, chunk_strategy)
        duration_ms = (time.perf_counter() - t0) * 1000

        self._idempotency.mark_processed(asset_id, tenant_id)

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


# ---------------------------------------------------------------------------
# Typing helper — not a real protocol import to avoid Python 3.7 compat issues
# ---------------------------------------------------------------------------

from typing import Callable  # noqa: E402

_ChunkerProtocol = Callable[[str, str, str], int]


__all__ = ["IngestAssetUseCase", "AssetAlreadyProcessedError"]
