"""MetricsCollector — per-request latency and token accumulator.

Collects pipeline stage latencies and LLM token counts during a single request,
then flushes them atomically to Prometheus on ``flush()``.

Design constraints:
  - ``flush()`` is idempotent: calling it twice must not double-count any metric.
  - ``degraded=True`` increments ``DEGRADED_MODE_ACTIVATIONS`` once per flush,
    not once per ``record_stage`` call.
  - The collector is not thread-safe — one instance per request context.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.observability.prometheus_metrics import (
    DEGRADED_MODE_ACTIVATIONS,
    QUERY_STAGE_LATENCY_MS,
    TOKENS_USED,
)
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_STAGE_FIELDS = ("classifier", "rag", "sql", "hybrid")


@dataclass
class MetricsCollector:
    """Accumulate per-request metrics and flush to Prometheus in one call.

    Usage::

        mc = MetricsCollector()
        mc.record_stage("rag", 123.4)
        mc.tokens_prompt = 512
        mc.tokens_completion = 128
        mc.flush()   # writes to Prometheus; safe to call again (no-op)
    """

    classifier_latency_ms: float | None = None
    rag_latency_ms: float | None = None
    sql_latency_ms: float | None = None
    hybrid_latency_ms: float | None = None

    tokens_prompt: int | None = None
    tokens_completion: int | None = None

    llm_provider: str | None = None
    degraded: bool = False

    _flushed: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_stage(self, stage: str, latency_ms: float) -> None:
        """Set the latency for *stage* (classifier | rag | sql | hybrid).

        Args:
            stage: One of ``"classifier"``, ``"rag"``, ``"sql"``, ``"hybrid"``.
            latency_ms: Elapsed time in milliseconds for that stage.

        Raises:
            ValueError: If *stage* is not one of the four recognised values.
        """
        if stage not in _STAGE_FIELDS:
            raise ValueError(
                f"Unknown stage {stage!r}. Must be one of {_STAGE_FIELDS}."
            )
        setattr(self, f"{stage}_latency_ms", latency_ms)

    def flush(self) -> None:
        """Write accumulated metrics to Prometheus.

        Idempotent: subsequent calls after the first are no-ops.
        """
        if self._flushed:
            return

        self._flush_latencies()
        self._flush_tokens()
        self._flush_degraded()

        self._flushed = True
        logger.info(
            "metrics_collector.flushed",
            provider=self.llm_provider,
            degraded=self.degraded,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _flush_latencies(self) -> None:
        for stage in _STAGE_FIELDS:
            value: float | None = getattr(self, f"{stage}_latency_ms")
            if value is not None:
                QUERY_STAGE_LATENCY_MS.labels(stage=stage).observe(value)

    def _flush_tokens(self) -> None:
        if self.tokens_prompt is not None:
            TOKENS_USED.labels(type="prompt").inc(self.tokens_prompt)
        if self.tokens_completion is not None:
            TOKENS_USED.labels(type="completion").inc(self.tokens_completion)

    def _flush_degraded(self) -> None:
        if self.degraded:
            DEGRADED_MODE_ACTIVATIONS.inc()


__all__ = ["MetricsCollector"]
