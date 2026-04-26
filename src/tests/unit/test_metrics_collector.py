"""Unit tests for MetricsCollector (Sprint 8 Task 9).

Coverage:
  TestRecordStage      — convenience setter, validation, all four stages
  TestFlushLatencies   — Prometheus histogram observations per stage
  TestFlushTokens      — prompt + completion counter increments
  TestFlushDegraded    — DEGRADED_MODE_ACTIVATIONS counter increment
  TestIdempotency      — flush() called twice must not double-count
  TestDefaults         — dataclass field defaults
"""
from __future__ import annotations

import pytest

from src.observability.metrics_collector import MetricsCollector
from src.observability.prometheus_metrics import (
    DEGRADED_MODE_ACTIVATIONS,
    QUERY_STAGE_LATENCY_MS,
    TOKENS_USED,
)


# ---------------------------------------------------------------------------
# TestDefaults
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_all_latency_fields_default_to_none(self):
        mc = MetricsCollector()
        assert mc.classifier_latency_ms is None
        assert mc.rag_latency_ms is None
        assert mc.sql_latency_ms is None
        assert mc.hybrid_latency_ms is None

    def test_token_fields_default_to_none(self):
        mc = MetricsCollector()
        assert mc.tokens_prompt is None
        assert mc.tokens_completion is None

    def test_llm_provider_defaults_to_none(self):
        mc = MetricsCollector()
        assert mc.llm_provider is None

    def test_degraded_defaults_to_false(self):
        mc = MetricsCollector()
        assert mc.degraded is False


# ---------------------------------------------------------------------------
# TestRecordStage
# ---------------------------------------------------------------------------

class TestRecordStage:
    def test_record_stage_sets_classifier_latency(self):
        mc = MetricsCollector()
        mc.record_stage("classifier", 42.5)
        assert mc.classifier_latency_ms == 42.5

    def test_record_stage_sets_rag_latency(self):
        mc = MetricsCollector()
        mc.record_stage("rag", 120.0)
        assert mc.rag_latency_ms == 120.0

    def test_record_stage_sets_sql_latency(self):
        mc = MetricsCollector()
        mc.record_stage("sql", 300.0)
        assert mc.sql_latency_ms == 300.0

    def test_record_stage_sets_hybrid_latency(self):
        mc = MetricsCollector()
        mc.record_stage("hybrid", 450.0)
        assert mc.hybrid_latency_ms == 450.0

    def test_record_stage_raises_on_unknown_stage(self):
        mc = MetricsCollector()
        with pytest.raises(ValueError, match="Unknown stage"):
            mc.record_stage("unknown_stage", 10.0)

    def test_record_stage_overwrites_previous_value(self):
        mc = MetricsCollector()
        mc.record_stage("rag", 100.0)
        mc.record_stage("rag", 200.0)
        assert mc.rag_latency_ms == 200.0


# ---------------------------------------------------------------------------
# TestFlushLatencies
# ---------------------------------------------------------------------------

class TestFlushLatencies:
    def test_flush_observes_rag_latency_into_histogram(self):
        mc = MetricsCollector(rag_latency_ms=150.0)
        before = QUERY_STAGE_LATENCY_MS.labels(stage="rag")._sum.get()
        mc.flush()
        after = QUERY_STAGE_LATENCY_MS.labels(stage="rag")._sum.get()
        assert after == pytest.approx(before + 150.0)

    def test_flush_observes_sql_latency_into_histogram(self):
        mc = MetricsCollector(sql_latency_ms=250.0)
        before = QUERY_STAGE_LATENCY_MS.labels(stage="sql")._sum.get()
        mc.flush()
        after = QUERY_STAGE_LATENCY_MS.labels(stage="sql")._sum.get()
        assert after == pytest.approx(before + 250.0)

    def test_flush_skips_none_latency_fields(self):
        mc = MetricsCollector()  # all None
        before = QUERY_STAGE_LATENCY_MS.labels(stage="hybrid")._sum.get()
        mc.flush()
        after = QUERY_STAGE_LATENCY_MS.labels(stage="hybrid")._sum.get()
        assert after == before  # no observation made

    def test_flush_observes_all_set_stages(self):
        mc = MetricsCollector(
            classifier_latency_ms=10.0,
            rag_latency_ms=100.0,
            sql_latency_ms=200.0,
            hybrid_latency_ms=300.0,
        )
        before_c = QUERY_STAGE_LATENCY_MS.labels(stage="classifier")._sum.get()
        mc.flush()
        after_c = QUERY_STAGE_LATENCY_MS.labels(stage="classifier")._sum.get()
        assert after_c == pytest.approx(before_c + 10.0)


# ---------------------------------------------------------------------------
# TestFlushTokens
# ---------------------------------------------------------------------------

class TestFlushTokens:
    def test_flush_increments_prompt_token_counter(self):
        mc = MetricsCollector(tokens_prompt=512)
        before = TOKENS_USED.labels(type="prompt")._value.get()
        mc.flush()
        after = TOKENS_USED.labels(type="prompt")._value.get()
        assert after == pytest.approx(before + 512)

    def test_flush_increments_completion_token_counter(self):
        mc = MetricsCollector(tokens_completion=128)
        before = TOKENS_USED.labels(type="completion")._value.get()
        mc.flush()
        after = TOKENS_USED.labels(type="completion")._value.get()
        assert after == pytest.approx(before + 128)

    def test_flush_skips_none_token_fields(self):
        mc = MetricsCollector()
        before_p = TOKENS_USED.labels(type="prompt")._value.get()
        before_c = TOKENS_USED.labels(type="completion")._value.get()
        mc.flush()
        assert TOKENS_USED.labels(type="prompt")._value.get() == before_p
        assert TOKENS_USED.labels(type="completion")._value.get() == before_c


# ---------------------------------------------------------------------------
# TestFlushDegraded
# ---------------------------------------------------------------------------

class TestFlushDegraded:
    def test_flush_increments_degraded_counter_when_degraded_true(self):
        mc = MetricsCollector(degraded=True)
        before = DEGRADED_MODE_ACTIVATIONS._value.get()
        mc.flush()
        after = DEGRADED_MODE_ACTIVATIONS._value.get()
        assert after == before + 1

    def test_flush_does_not_increment_degraded_counter_when_false(self):
        mc = MetricsCollector(degraded=False)
        before = DEGRADED_MODE_ACTIVATIONS._value.get()
        mc.flush()
        after = DEGRADED_MODE_ACTIVATIONS._value.get()
        assert after == before


# ---------------------------------------------------------------------------
# TestIdempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_flush_twice_does_not_double_count_latency(self):
        mc = MetricsCollector(rag_latency_ms=99.0)
        before = QUERY_STAGE_LATENCY_MS.labels(stage="rag")._sum.get()
        mc.flush()
        mc.flush()
        after = QUERY_STAGE_LATENCY_MS.labels(stage="rag")._sum.get()
        assert after == pytest.approx(before + 99.0)

    def test_flush_twice_does_not_double_count_tokens(self):
        mc = MetricsCollector(tokens_prompt=100, tokens_completion=50)
        before_p = TOKENS_USED.labels(type="prompt")._value.get()
        before_c = TOKENS_USED.labels(type="completion")._value.get()
        mc.flush()
        mc.flush()
        assert TOKENS_USED.labels(type="prompt")._value.get() == pytest.approx(before_p + 100)
        assert TOKENS_USED.labels(type="completion")._value.get() == pytest.approx(before_c + 50)

    def test_flush_twice_does_not_double_count_degraded(self):
        mc = MetricsCollector(degraded=True)
        before = DEGRADED_MODE_ACTIVATIONS._value.get()
        mc.flush()
        mc.flush()
        after = DEGRADED_MODE_ACTIVATIONS._value.get()
        assert after == before + 1

    def test_flush_ten_times_still_counts_once(self):
        mc = MetricsCollector(tokens_prompt=1)
        before = TOKENS_USED.labels(type="prompt")._value.get()
        for _ in range(10):
            mc.flush()
        after = TOKENS_USED.labels(type="prompt")._value.get()
        assert after == pytest.approx(before + 1)
