"""DegradedModePort — abstract interface for the degraded-mode answer cache.

Concrete implementation: ``src/infrastructure/generation/degraded_mode_service.py``.
The cache maps a stable query hash (SHA-256 of the normalised prompt) to the
last known successful answer. When all LLM providers fail, the service returns
the cached answer instead of raising an error, keeping the system partially
functional.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class DegradedModePort(ABC):
    """Read and write the per-query answer cache used in degraded mode."""

    @abstractmethod
    def get_cached(self, query_hash: str) -> str | None:
        """Return the cached answer for *query_hash*, or ``None`` if absent."""
        ...

    @abstractmethod
    def set_cached(self, query_hash: str, answer: str) -> None:
        """Store *answer* under *query_hash* for future degraded-mode lookups."""
        ...


__all__ = ["DegradedModePort"]
