"""
observability — Prometheus metrics and structured JSON logging for ERP Agentic RAG.

Exposes:
    get_logger          — structured JSON logger with trace_id propagation
    prometheus_metrics  — all Prometheus counters and histograms
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "get_logger",
    "prometheus_metrics",
]


def get_logger(name: str):  # noqa: ANN201 — return type declared in structured_logger
    """Lazy import to avoid circular dependency at module init time."""
    from src.observability.structured_logger import get_logger as _get_logger

    return _get_logger(name)
