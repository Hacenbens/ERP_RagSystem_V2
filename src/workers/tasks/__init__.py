"""
Worker tasks package.

Tasks:
    ingest_asset  — chunk a document and store chunks in MongoDB  (Sprint 6)
    embed_asset   — vectorise chunks and store in Milvus           (Sprint 6)
"""
from __future__ import annotations

from src.workers.tasks.ingest_task import ingest_asset

__all__ = ["ingest_asset"]
