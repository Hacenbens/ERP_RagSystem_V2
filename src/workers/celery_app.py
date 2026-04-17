"""
Celery application factory for ERP Agentic RAG.

Transport  : Redis  — CELERY_BROKER_URL   (default: redis://localhost:6379/0)
Backend    : Redis  — CELERY_RESULT_BACKEND (default: redis://localhost:6379/1)

Design constraints enforced at the transport layer:

  task_serializer = "json"
    Only JSON-serialisable arguments may be passed to tasks.
    This is the technical enforcement of the "pass IDs, not objects" rule —
    passing a full document object would fail serialisation at call-site.

  task_acks_late = True
    The broker message is acknowledged AFTER the task finishes (not before).
    If the worker process dies mid-execution the message is re-queued.

  task_reject_on_worker_lost = True
    If the worker process is killed (OOM, SIGKILL) the task is re-queued
    rather than silently dropped.

  worker_prefetch_multiplier = 1
    Each worker process holds at most one un-acked task.
    Prevents a slow ingest_task from starving short embed_tasks on the
    same worker, and keeps memory usage predictable.

  task_track_started = True
    Enables the STARTED state so GET /admin/jobs/{id} can distinguish
    "waiting in queue" from "currently running".

  task_always_eager = False  (default, overridden to True in test config)
    In tests: set CELERY_TASK_ALWAYS_EAGER=true to execute tasks inline
    (synchronous, no broker required).
"""
from __future__ import annotations

import os

from celery import Celery

# ---------------------------------------------------------------------------
# Environment-driven configuration
# ---------------------------------------------------------------------------

_BROKER_URL: str = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
_RESULT_BACKEND: str = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# Set by conftest.py in tests: "true" / "1" → task_always_eager mode
_ALWAYS_EAGER: bool = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "false").lower() in (
    "true",
    "1",
)

# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------


def create_celery_app() -> Celery:
    """Create and configure the Celery application.

    Returns a fully configured Celery instance.  Call this once at module
    level; the returned object is imported everywhere else.
    """
    app = Celery("erp_rag")

    app.conf.update(
        # ── Broker / backend ────────────────────────────────────────────────
        broker_url=_BROKER_URL,
        result_backend=_RESULT_BACKEND,
        # ── Serialisation — enforce "pass IDs not objects" at transport ─────
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # ── Reliability ─────────────────────────────────────────────────────
        task_acks_late=True,                # ack AFTER execution
        task_reject_on_worker_lost=True,    # re-queue if worker dies
        worker_prefetch_multiplier=1,       # one task per worker at a time
        # ── Observability ───────────────────────────────────────────────────
        task_track_started=True,            # expose STARTED state for polling
        # ── Result expiry ───────────────────────────────────────────────────
        result_expires=86_400,              # keep results 24 h
        # ── Timezone ────────────────────────────────────────────────────────
        timezone="UTC",
        enable_utc=True,
        # ── Test mode (no-op when False) ─────────────────────────────────
        task_always_eager=_ALWAYS_EAGER,
        task_eager_propagates=_ALWAYS_EAGER,  # surface exceptions in eager mode
    )

    # Auto-discover tasks inside src/workers/tasks/
    app.autodiscover_tasks(["src.workers.tasks"])

    return app


# Module-level singleton — imported by all task modules
celery_app: Celery = create_celery_app()

__all__ = ["celery_app", "create_celery_app"]
