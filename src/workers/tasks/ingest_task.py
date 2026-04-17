"""
Celery task: ingest_asset
=========================

Thin orchestration layer — receives IDs, resolves dependencies from the DI
container, delegates business logic to IngestAssetUseCase, and handles all
Celery-specific concerns: retries, dead-letter, metrics.

Responsibilities of THIS file only
------------------------------------
  - Declare the @celery_app.task decorator (retry limits, time limits)
  - Resolve ``ingest_use_case`` and ``dead_letter_repository`` from the container
  - Apply exponential-backoff countdown on each retry
  - Write a FailedTaskEntry to the dead-letter repo on MaxRetriesExceededError
  - Emit Prometheus metrics: dispatched / failed / duration

All other concerns live elsewhere
-----------------------------------
  src/domain/ingest.py                                ← domain models
  src/domain/ports/dead_letter_repository.py          ← port interface
  src/domain/ports/idempotency_store.py               ← port interface
  src/infrastructure/workers/dead_letter_repository.py ← implementations
  src/infrastructure/workers/idempotency_store.py      ← implementations
  src/use_cases/tasks/ingest_asset_use_case.py         ← business logic
  src/infrastructure/di/factory.py                     ← dependency wiring
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from src.domain.ingest import FailedTaskEntry
from src.infrastructure.di.factory import get_worker_container
from src.observability.prometheus_metrics import (
    WORKER_TASK_DURATION,
    WORKER_TASKS_DISPATCHED,
    WORKER_TASKS_FAILED,
)
from src.observability.structured_logger import get_logger
from src.use_cases.tasks.ingest_asset_use_case import AssetAlreadyProcessedError
from src.workers.celery_app import celery_app

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_NAME: str = "workers.tasks.ingest_asset"
MAX_RETRIES: int = 3
BASE_RETRY_DELAY_SECONDS: int = 30   # attempt 0 → 30 s, 1 → 60 s, 2 → 120 s
MAX_RETRY_DELAY_SECONDS: int = 600   # hard ceiling (10 minutes)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name=TASK_NAME,
    # ── Retry policy ──────────────────────────────────────────────────────
    max_retries=MAX_RETRIES,
    # Countdown is computed per attempt (exponential backoff) — no static default
    #
    # ── Time limits ───────────────────────────────────────────────────────
    time_limit=300,         # hard kill after 5 minutes
    soft_time_limit=240,    # SoftTimeLimitExceeded raised at 4 minutes for graceful cleanup
    #
    # ── Reliability (declared explicitly for self-documentation) ──────────
    acks_late=True,
)
def ingest_asset(
    self: Task,
    asset_id: str,
    tenant_id: str,
    chunk_strategy: str = "sop",
) -> dict[str, Any]:
    """Ingest a document asset — accepts IDs only, never full objects.

    Args:
        asset_id:       Unique identifier of the asset to ingest.
        tenant_id:      Tenant that owns the asset (isolation key).
        chunk_strategy: One of ``"sop"`` | ``"bpmn"`` | ``"tax_circular"``.

    Returns:
        JSON-serialisable dict describing the outcome (success / skipped).

    Retry behaviour:
        Transient failures trigger up to 3 retries with exponential backoff
        (30 s → 60 s → 120 s).  On final failure a FailedTaskEntry is written
        to the dead-letter repository and the task state is set to FAILURE.
    """
    task_id: str = self.request.id or str(uuid4())

    logger.info(
        "ingest_task.received",
        task_id=task_id,
        asset_id=asset_id,
        tenant_id=tenant_id,
        chunk_strategy=chunk_strategy,
        attempt=self.request.retries + 1,
        max_attempts=MAX_RETRIES + 1,
    )
    WORKER_TASKS_DISPATCHED.labels(task_name=TASK_NAME).inc()

    # Resolve dependencies from the DI container (built once per worker process)
    container = get_worker_container()
    use_case = container.get("ingest_use_case")
    dead_letter_repo = container.get("dead_letter_repository")

    try:
        result = use_case.execute(
            asset_id=asset_id,
            tenant_id=tenant_id,
            chunk_strategy=chunk_strategy,
            task_id=task_id,
        )
        WORKER_TASK_DURATION.labels(task_name=TASK_NAME).observe(
            result.duration_ms / 1000
        )
        return {
            "status": "success",
            "asset_id": result.asset_id,
            "tenant_id": result.tenant_id,
            "chunk_count": result.chunk_count,
            "chunk_strategy": result.chunk_strategy,
            "duration_ms": result.duration_ms,
            "task_id": task_id,
        }

    except AssetAlreadyProcessedError:
        return {
            "status": "skipped",
            "reason": "already_processed",
            "asset_id": asset_id,
            "tenant_id": tenant_id,
            "task_id": task_id,
        }

    except SoftTimeLimitExceeded:
        logger.error(
            "ingest_task.soft_time_limit",
            task_id=task_id,
            asset_id=asset_id,
            tenant_id=tenant_id,
        )
        raise RuntimeError(
            f"ingest_asset soft time limit exceeded for asset_id={asset_id!r}"
        )

    except Exception as exc:
        countdown = min(
            BASE_RETRY_DELAY_SECONDS * (2 ** self.request.retries),
            MAX_RETRY_DELAY_SECONDS,
        )  # 30 s → 60 s → 120 s, capped at 600 s

        if self.request.retries >= MAX_RETRIES:
            # Retry budget exhausted — write dead-letter and fail permanently.
            # Note: self.retry(exc=exc) when max exceeded raises the *original*
            # exc, not MaxRetriesExceededError, so we check the counter directly.
            logger.error(
                "ingest_task.dead_letter",
                task_id=task_id,
                asset_id=asset_id,
                tenant_id=tenant_id,
                retry_count=MAX_RETRIES,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            _write_dead_letter(
                dead_letter_repo=dead_letter_repo,
                task_id=task_id,
                asset_id=asset_id,
                tenant_id=tenant_id,
                chunk_strategy=chunk_strategy,
                exc_type=type(exc).__name__,
                exc_message=str(exc),
            )
            WORKER_TASKS_FAILED.labels(task_name=TASK_NAME).inc()
            raise

        logger.warning(
            "ingest_task.retry",
            task_id=task_id,
            asset_id=asset_id,
            tenant_id=tenant_id,
            attempt=self.request.retries + 1,
            max_retries=MAX_RETRIES,
            countdown_s=countdown,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _write_dead_letter(
    *,
    dead_letter_repo: Any,
    task_id: str,
    asset_id: str,
    tenant_id: str,
    chunk_strategy: str,
    exc_type: str,
    exc_message: str,
) -> None:
    """Build a FailedTaskEntry and persist it via the dead-letter port."""
    entry = FailedTaskEntry(
        id=str(uuid4()),
        task_id=task_id,
        task_name=TASK_NAME,
        asset_id=asset_id,
        tenant_id=tenant_id,
        chunk_strategy=chunk_strategy,
        exception_type=exc_type,
        exception_message=exc_message,
        retry_count=MAX_RETRIES,
        failed_at=datetime.now(timezone.utc).isoformat(),
        args={
            "asset_id": asset_id,
            "tenant_id": tenant_id,
            "chunk_strategy": chunk_strategy,
        },
    )
    dead_letter_repo.save(entry)


__all__ = [
    "ingest_asset",
    "TASK_NAME",
    "MAX_RETRIES",
    "BASE_RETRY_DELAY_SECONDS",
    "MAX_RETRY_DELAY_SECONDS",
]
