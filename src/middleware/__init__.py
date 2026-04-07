"""Middleware stack for ERP Agentic RAG.

Execution order (outermost → innermost):
    LoggingMiddleware → AuthMiddleware → RateLimitMiddleware
    → RBACMiddleware → PIIMaskingMiddleware → route handler
"""
from __future__ import annotations

__all__ = [
    "LoggingMiddleware",
]
