"""
Worker tasks package.

Tasks:
    ingest_asset  — chunk a document and store chunks in MongoDB  (Sprint 6)
    embed_asset   — vectorise chunks and store in Milvus           (Sprint 6)

Importing both here is what registers them with Celery. celery_app calls
autodiscover_tasks on this package, which imports this module and nothing
deeper, so a task missing from these imports is never registered — the worker
starts cleanly, advertises only what it found, and any message for the missing
task is rejected as NotRegistered.

embed_asset was absent, so ingest dispatched an embed job that no worker could
execute: chunks were written and nothing was ever vectorised.
"""
from __future__ import annotations

from src.infrastructure.workers.tasks.embed_task import embed_asset
from src.infrastructure.workers.tasks.ingest_task import ingest_asset

__all__ = ["embed_asset", "ingest_asset"]
