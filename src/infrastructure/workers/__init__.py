"""
Workers package — Celery-based async task processing for ERP Agentic RAG.

Exposes:
    celery_app   — the configured Celery application instance
    ingest_asset — document ingestion task (chunk + store)
"""
from __future__ import annotations

from src.infrastructure.workers.celery_app import celery_app

__all__ = ["celery_app"]
