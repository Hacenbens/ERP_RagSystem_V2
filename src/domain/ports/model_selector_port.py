"""ModelSelectorPort — abstract interface for LLM provider selection.

Concrete implementation: ``src/infrastructure/generation/model_selector.py``.
The selector wraps multiple ``LLMPort`` providers (e.g. OpenAI primary,
vLLM fallback) and exposes a single ``complete()`` entry point that applies
a circuit-breaker and automatic failover policy.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ModelSelectorPort(ABC):
    """Select an available LLM provider and forward completion requests.

    Implementations must:
    - Try providers in priority order (primary → fallback).
    - Track consecutive failures per provider.
    - Open the circuit after ``_MAX_FAILURES`` consecutive failures and hold
      it open for ``_OPEN_DURATION_S`` seconds before retrying.
    - Increment ``LLM_FAILURE_RATE`` and update ``CIRCUIT_BREAKER_STATE``
      on every provider-level failure.
    - Raise ``LLMUnavailableError`` only when *all* providers are exhausted.
    """

    @abstractmethod
    def complete(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Return a text completion, selecting from available providers.

        Raises:
            LLMUnavailableError: if every configured provider fails or has
                an open circuit breaker.
        """
        ...


__all__ = ["ModelSelectorPort"]
