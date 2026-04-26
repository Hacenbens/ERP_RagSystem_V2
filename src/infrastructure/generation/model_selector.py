"""ModelSelector — LLMPort implementation that fans out to multiple providers.

Wraps an ordered list of ``(LLMPort, provider_name)`` pairs and exposes a
single ``complete()`` entry point.  For each call it:

1. Skips any provider whose ``CircuitBreaker`` is open.
2. Delegates to the first available provider.
3. On ``ConnectionError``: records the failure in the breaker and tries next.
4. On success: records success in the breaker and returns the answer.
5. When all providers are exhausted: raises ``LLMUnavailableError``.

The circuit-breaker logic (failure counting, timing, Prometheus updates) lives
entirely in ``circuit_breaker.py`` — this class is only responsible for
provider selection and fallback orchestration.
"""
from __future__ import annotations

from src.domain.exceptions import LLMUnavailableError
from src.domain.ports.llm_port import LLMPort
from src.infrastructure.generation.circuit_breaker import CircuitBreaker
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class ModelSelector(LLMPort):
    """Select an available LLM provider with automatic fallback.

    Usage::

        selector = ModelSelector(
            providers=[
                (gemini_client, "gemini"),
                (vllm_client,   "vllm"),
            ]
        )
        answer = selector.complete(prompt)

    Raises:
        LLMUnavailableError: if every provider's circuit is open or raises
            ``ConnectionError``.
    """

    def __init__(
        self,
        providers: list[tuple[LLMPort, str]],
        max_failures: int = 5,
        open_duration_s: float = 60.0,
    ) -> None:
        """Initialise with an ordered list of ``(provider, name)`` pairs.

        Args:
            providers: Ordered ``(LLMPort, label)`` list — first entry is
                primary, subsequent entries are fallbacks.
            max_failures: Consecutive failures before opening the circuit.
            open_duration_s: Seconds the circuit stays open before a
                half-open retry is allowed.
        """
        self._slots: list[tuple[LLMPort, CircuitBreaker]] = [
            (provider, CircuitBreaker(name, max_failures, open_duration_s))
            for provider, name in providers
        ]

    # ------------------------------------------------------------------
    # Public API — exposed for tests and DegradedModeService
    # ------------------------------------------------------------------

    @property
    def breakers(self) -> dict[str, CircuitBreaker]:
        """Return a mapping of provider name → CircuitBreaker for inspection."""
        return {cb.provider_name: cb for _, cb in self._slots}

    # ------------------------------------------------------------------
    # LLMPort implementation
    # ------------------------------------------------------------------

    def complete(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Return a completion from the first available provider.

        Raises:
            LLMUnavailableError: when all providers are exhausted.
        """
        last_exc: Exception | None = None

        for provider, breaker in self._slots:
            if breaker.is_open():
                logger.info(
                    "model_selector.skip_open_circuit",
                    provider=breaker.provider_name,
                )
                continue

            logger.info(
                "model_selector.attempt",
                provider=breaker.provider_name,
                prompt_len=len(prompt),
            )
            try:
                answer = provider.complete(prompt, temperature, max_tokens)
                breaker.record_success()
                logger.info(
                    "model_selector.success",
                    provider=breaker.provider_name,
                    answer_len=len(answer),
                )
                return answer

            except ConnectionError as exc:
                last_exc = exc
                breaker.record_failure()
                logger.error(
                    "model_selector.provider_failed",
                    provider=breaker.provider_name,
                    error=str(exc),
                )

        raise LLMUnavailableError(
            f"All LLM providers exhausted. Last error: {last_exc}"
        ) from last_exc


__all__ = ["ModelSelector"]
