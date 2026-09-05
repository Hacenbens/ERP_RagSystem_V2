"""Timing and token accounting for the query pipeline.

Two things live here, because both were previously done by hand at every call
site and drifted.

**Stage latency.** ``stage_timer`` is the one way a pipeline stage reports how
long it took. Before this, eight modules each wrote their own
``t0 = time.perf_counter() ... (time.perf_counter() - t0) * 1000``, and the
ones that reached Prometheus disagreed about units — Stage 1 recorded seconds
into a metric of its own while everything else recorded nothing at all.

**Tokens.** ``record_tokens`` is called by the LLM clients, which are the only
layer that sees what a provider actually charged for. Counting tokens higher up
means estimating them, and an estimate reported as a measurement is worse than
no number.

Why not the previous design
---------------------------
This replaces ``MetricsCollector``, a per-request accumulator with a
``flush()``. It was written, tested, and never called once: using it meant
constructing one per request and threading it through the route, the router,
the use case, and the agent, so nothing ever did. Recording at the point where
the work happens needs no plumbing, which is the only reason this version is
wired and that one was not.

The cost of that choice is that a stage's timings are not grouped per request.
Prometheus aggregates rather than joining, so per-request correlation belongs in
the trace_id already on every log line, not in a metric.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

from src.observability.prometheus_metrics import QUERY_STAGE_LATENCY_MS, TOKENS_USED
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class Stage(str, Enum):
    """Stages of the query pipeline that report latency.

    A closed set on purpose. Passing a raw string would let a typo mint a new
    time series that looks like data and is never queried, which is how
    ``erp_rag_classifier_accuracy`` sat on the dashboard reporting zero.
    """

    CLASSIFY     = "classify"       # NL query → routing decision
    RETRIEVE     = "retrieve"       # embed query + vector search
    RERANK       = "rerank"         # cross-encoder re-scoring
    GENERATE     = "generate"       # RAG answer generation
    MERGE        = "merge"          # hybrid RAG+SQL answer merge
    SQL_GENERATE = "sql_generate"   # NL → SQL  (was SQL_STAGE1_LATENCY)
    SQL_EXECUTE  = "sql_execute"    # SQL → rows


@dataclass
class Timing:
    """How long a stage has taken.

    ``elapsed_ms`` reads correctly both inside the ``with`` block and after it:
    live while the block runs, frozen at the final value once it exits. A
    version that only filled the field on exit silently logged 0.0 for every
    call site that reported latency from inside its own block, so the trap is
    removed rather than documented.
    """

    _started: float
    _final_ms: float | None = None

    @property
    def elapsed_ms(self) -> float:
        if self._final_ms is not None:
            return self._final_ms
        return (time.perf_counter() - self._started) * 1000


@contextmanager
def stage_timer(stage: Stage) -> Iterator[Timing]:
    """Time a pipeline stage and record it to Prometheus.

    The timing is recorded in a ``finally``, so a stage that raises is still
    measured. A stage that fails slowly is the one worth seeing, and dropping
    those leaves a histogram that describes only the happy path.

    Usage::

        with stage_timer(Stage.RETRIEVE) as t:
            chunks = retriever.retrieve(...)
        logger.info("done", latency_ms=round(t.elapsed_ms, 2))
    """
    timing = Timing(_started=time.perf_counter())
    try:
        yield timing
    finally:
        timing._final_ms = timing.elapsed_ms
        QUERY_STAGE_LATENCY_MS.labels(stage=stage.value).observe(timing._final_ms)


def record_tokens(provider: str, prompt: int | None, completion: int | None) -> None:
    """Record the tokens a provider reported for one completion.

    ``None`` means the provider did not report that count, which is different
    from reporting zero: a missing number must not be recorded as zero usage.
    Both are skipped rather than defaulted.

    Never raises. Token accounting failing is not a reason for a user's query
    to fail, so a bad count is logged and dropped.
    """
    try:
        if prompt is not None and prompt > 0:
            TOKENS_USED.labels(provider=provider, type="prompt").inc(prompt)
        if completion is not None and completion > 0:
            TOKENS_USED.labels(provider=provider, type="completion").inc(completion)
    except Exception as exc:  # noqa: BLE001 — metrics must never break a request
        logger.warning(
            "tokens.record_failed",
            provider=provider,
            error=str(exc),
        )


__all__ = ["Stage", "Timing", "record_tokens", "stage_timer"]
