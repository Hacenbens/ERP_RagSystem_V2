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

import hashlib
import json

from src.domain.exceptions import LLMUnavailableError
from src.domain.ports.degraded_mode_port import DegradedModePort
from src.domain.ports.llm_port import LLMPort
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

    def complete(
        self,
        prompt: str,
        query_hash: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Return a completion, falling back to cache or a degraded response.

        Args:
            prompt: The full prompt string forwarded to the LLM.
            query_hash: A stable identifier for this query used as the cache key.
            temperature: Forwarded to the provider.
            max_tokens: Forwarded to the provider.

        Returns:
            The LLM answer string, a previously cached answer, or a degraded-mode
            JSON string — always a ``str``, never raises.

        The generation parameters are keyword-only so the original positional
        ``complete(prompt, query_hash)`` calls keep working. They used to be
        dropped entirely: every prompt reached the provider at the selector's
        defaults, ignoring the per-prompt temperature and max_tokens that
        PromptRegistry resolves.
        """
        try:
            answer = self._selector.complete(prompt, temperature, max_tokens)
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


def query_hash(prompt: str) -> str:
    """Return the cache key for *prompt* — SHA-256 of its normalised text.

    Normalisation collapses surrounding whitespace only. Two requests that
    resolve to the same prompt share a cache entry, which is what makes a
    cached answer available during an outage.
    """
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


class DegradedModeLLM(LLMPort):
    """LLMPort adapter that degrades instead of raising.

    DegradedModeService predates LLMPort and takes an explicit query_hash, so
    it could not be injected anywhere an LLMPort was expected — which is why
    Sprint 8's degraded mode shipped complete, tested, and wired to nothing.
    This adapter derives the hash from the prompt and presents the standard
    port, so the DI container can place it wherever a raw ModelSelector went.

    Being an LLMPort that never raises is the point: LLMUnavailableError
    reaching a route handler is an unhandled 500, whereas a degraded answer
    is a response the caller can render.
    """

    def __init__(self, service: DegradedModeService) -> None:
        self._service = service

    def complete(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Return a completion, a cached answer, or the degraded response."""
        return self._service.complete(
            prompt,
            query_hash(prompt),
            temperature=temperature,
            max_tokens=max_tokens,
        )


__all__ = ["DegradedModeService", "DegradedModeLLM", "query_hash"]
