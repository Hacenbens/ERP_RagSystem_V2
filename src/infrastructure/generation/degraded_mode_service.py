"""DegradedModeService — cache-backed LLM wrapper with graceful degradation.

Wraps a ``ModelSelector`` and exposes a ``complete(prompt, query_hash)`` entry
point.  On success the answer is stored in an in-memory cache keyed by
``query_hash``.  When ``LLMUnavailableError`` is raised (all providers
exhausted) the service:

1. Increments ``DEGRADED_MODE_ACTIVATIONS``.
2. Returns the cached answer for that hash when one exists.
3. Otherwise returns a well-formed degraded-mode JSON string so callers always
   receive a string (never an exception propagating into the HTTP layer).

The ``cache`` dict is constructor-injectable so tests can inspect or seed it.
"""
from __future__ import annotations

import json

from src.domain.exceptions import LLMUnavailableError
from src.domain.ports.degraded_mode_port import DegradedModePort
from src.infrastructure.generation.model_selector import ModelSelector
from src.observability.prometheus_metrics import DEGRADED_MODE_ACTIVATIONS
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_UNAVAILABLE_RESPONSE = json.dumps(
    {"degraded": True, "cached_answer": None, "answer": "Service temporarily unavailable."}
)


class DegradedModeService(DegradedModePort):
    """LLM facade that falls back to a cached answer when all providers fail.

    Args:
        selector: A ``ModelSelector`` (or any ``LLMPort`` implementation).
        cache: Optional pre-seeded ``{query_hash: answer}`` dict.  Defaults to
            an empty dict; mutated in-place so callers can inspect it.
    """

    def __init__(
        self,
        selector: ModelSelector,
        cache: dict[str, str] | None = None,
    ) -> None:
        self._selector = selector
        self._cache: dict[str, str] = cache if cache is not None else {}

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def complete(self, prompt: str, query_hash: str) -> str:
        """Return a completion, falling back to cache or a degraded response.

        Args:
            prompt: The full prompt string forwarded to the LLM.
            query_hash: A stable identifier for this query used as the cache key.

        Returns:
            The LLM answer string, a previously cached answer, or a degraded-mode
            JSON string — always a ``str``, never raises.
        """
        try:
            answer = self._selector.complete(prompt)
            self.set_cached(query_hash, answer)
            return answer

        except LLMUnavailableError:
            DEGRADED_MODE_ACTIVATIONS.inc()
            cached = self.get_cached(query_hash)
            cache_hit = cached is not None

            logger.warning(
                "degraded_mode.activated",
                query_hash=query_hash,
                cache_hit=cache_hit,
            )

            return cached if cached is not None else _UNAVAILABLE_RESPONSE

    # ------------------------------------------------------------------
    # DegradedModePort implementation
    # ------------------------------------------------------------------

    def get_cached(self, query_hash: str) -> str | None:
        """Return the cached answer for *query_hash*, or ``None``."""
        return self._cache.get(query_hash)

    def set_cached(self, query_hash: str, answer: str) -> None:
        """Store *answer* under *query_hash* in the in-memory cache."""
        self._cache[query_hash] = answer


__all__ = ["DegradedModeService"]
