"""CircuitBreaker — per-provider failure state machine for the ModelSelector.

States:
  CLOSED    — normal operation; consecutive failure count below threshold.
  OPEN      — all calls blocked; entered after ``max_failures`` consecutive errors.
  HALF-OPEN — one attempt allowed after ``open_duration_s`` elapses; resets on success.

Prometheus metrics updated on every state transition:
  - ``LLM_FAILURE_RATE.labels(provider=name)``    — incremented on each failure.
  - ``CIRCUIT_BREAKER_STATE.labels(provider=name)`` — set to 1 on open, 0 on close.
"""
from __future__ import annotations

import time

from src.observability.prometheus_metrics import CIRCUIT_BREAKER_STATE, LLM_FAILURE_RATE
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class CircuitBreaker:
    """Track consecutive failures for one LLM provider and block when threshold is reached."""

    def __init__(
        self,
        provider_name: str,
        max_failures: int = 5,
        open_duration_s: float = 60.0,
    ) -> None:
        self.provider_name = provider_name
        self._max_failures = max_failures
        self._open_duration_s = open_duration_s
        self._failure_count: int = 0
        self._opened_at: float | None = None

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """Return ``True`` if the circuit is open and the cooldown has not elapsed.

        Automatically transitions to HALF-OPEN (and resets counters) when
        ``open_duration_s`` seconds have passed since the circuit was opened.
        """
        if self._opened_at is None:
            return False

        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self._open_duration_s:
            self._opened_at = None
            self._failure_count = 0
            CIRCUIT_BREAKER_STATE.labels(provider=self.provider_name).set(0)
            logger.info(
                "circuit_breaker.half_open",
                provider=self.provider_name,
                elapsed_s=round(elapsed, 1),
            )
            return False

        return True

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        """Reset the failure counter and close the circuit."""
        was_open = self._opened_at is not None
        self._failure_count = 0
        self._opened_at = None
        CIRCUIT_BREAKER_STATE.labels(provider=self.provider_name).set(0)
        if was_open:
            logger.info("circuit_breaker.closed", provider=self.provider_name)

    def record_failure(self) -> None:
        """Increment the failure counter and open the circuit when the threshold is reached."""
        self._failure_count += 1
        LLM_FAILURE_RATE.labels(provider=self.provider_name).inc()

        if self._failure_count >= self._max_failures and self._opened_at is None:
            self._opened_at = time.monotonic()
            CIRCUIT_BREAKER_STATE.labels(provider=self.provider_name).set(1)
            logger.warning(
                "circuit_breaker.opened",
                provider=self.provider_name,
                failure_count=self._failure_count,
                threshold=self._max_failures,
            )
        else:
            logger.warning(
                "circuit_breaker.failure_recorded",
                provider=self.provider_name,
                failure_count=self._failure_count,
                threshold=self._max_failures,
            )

    # ------------------------------------------------------------------
    # Inspection helpers (used by tests and ModelSelector logging)
    # ------------------------------------------------------------------

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._failure_count

    @property
    def opened_at(self) -> float | None:
        """``time.monotonic()`` timestamp when the circuit was opened, or ``None``."""
        return self._opened_at


__all__ = ["CircuitBreaker"]
