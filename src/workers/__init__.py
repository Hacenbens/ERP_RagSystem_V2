"""
Workers package — Celery-based async task processing for ERP Agentic RAG.

Exposes:
    celery_app  — the configured Celery application instance
    ingest_asset — document ingestion task (chunk + store)
    embed_asset  — vectorisation task (Sprint 6 Task 2)
"""
from __future__ import annotations

from src.workers.celery_app import celery_app

__all__ = ["celery_app"]
