"""Unit tests for ModelSelector and CircuitBreaker (Sprint 8 Task 5).

Coverage:
  TestModelSelectorFallback   — provider ordering, fallback, error propagation
  TestModelSelectorCounters   — Prometheus LLM_FAILURE_RATE increments
  TestCircuitBreakerState     — open/closed/half-open transitions
  TestCircuitBreakerTiming    — 60-second cooldown with mocked time.monotonic
  TestCircuitBreakerIsolation — independent breakers per ModelSelector instance
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.domain.exceptions import LLMUnavailableError
from src.domain.ports.llm_port import LLMPort
from src.infrastructure.generation.circuit_breaker import CircuitBreaker
from src.infrastructure.generation.model_selector import ModelSelector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(answer: str | None = None, raises: bool = False) -> MagicMock:
    mock = MagicMock(spec=LLMPort)
    if raises:
        mock.complete.side_effect = ConnectionError("provider down")
    else:
        mock.complete.return_value = answer or "ok"
    return mock


def _make_selector(*pairs: tuple[MagicMock, str], **kwargs) -> ModelSelector:
    return ModelSelector(providers=list(pairs), **kwargs)


# ---------------------------------------------------------------------------
# TestModelSelectorFallback
# ---------------------------------------------------------------------------

class TestModelSelectorFallback:
    def test_primary_success_returns_answer_without_calling_fallback(self):
        primary = _make_provider("from primary")
        fallback = _make_provider("from fallback")
        sel = _make_selector((primary, "primary"), (fallback, "fallback"))

        result = sel.complete("q")

        assert result == "from primary"
        fallback.complete.assert_not_called()

    def test_primary_connection_error_triggers_fallback(self):
        primary = _make_provider(raises=True)
        fallback = _make_provider("fallback answer")
        sel = _make_selector((primary, "primary"), (fallback, "fallback"))

        result = sel.complete("q")

        assert result == "fallback answer"
        fallback.complete.assert_called_once()

    def test_both_providers_fail_raises_llm_unavailable_error(self):
        sel = _make_selector(
            (_make_provider(raises=True), "p1"),
            (_make_provider(raises=True), "p2"),
        )
        with pytest.raises(LLMUnavailableError):
            sel.complete("q")

    def test_single_provider_success_returns_answer(self):
        sel = _make_selector((_make_provider("solo"), "solo"))
        assert sel.complete("q") == "solo"

    def test_single_provider_failure_raises_llm_unavailable_error(self):
        sel = _make_selector((_make_provider(raises=True), "solo"))
        with pytest.raises(LLMUnavailableError):
            sel.complete("q")

    def test_primary_called_with_prompt_and_defaults(self):
        primary = _make_provider("ans")
        sel = _make_selector((primary, "p"))
        sel.complete("my prompt")
        primary.complete.assert_called_once_with("my prompt", 0.0, 512)

    def test_temperature_and_max_tokens_forwarded(self):
        primary = _make_provider("ans")
        sel = _make_selector((primary, "p"))
        sel.complete("q", temperature=0.7, max_tokens=256)
        primary.complete.assert_called_once_with("q", 0.7, 256)

    def test_llm_unavailable_error_message_contains_last_error(self):
        sel = _make_selector((_make_provider(raises=True), "p"))
        with pytest.raises(LLMUnavailableError, match="provider down"):
            sel.complete("q")


# ---------------------------------------------------------------------------
# TestModelSelectorCounters — Prometheus LLM_FAILURE_RATE
# ---------------------------------------------------------------------------

class TestModelSelectorCounters:
    def test_primary_failure_increments_llm_failure_rate_counter(self):
        from src.observability.prometheus_metrics import LLM_FAILURE_RATE

        before = LLM_FAILURE_RATE.labels(provider="primary")._value.get()
        sel = _make_selector(
            (_make_provider(raises=True), "primary"),
            (_make_provider("ok"), "fallback"),
            max_failures=99,
        )
        sel.complete("q")
        after = LLM_FAILURE_RATE.labels(provider="primary")._value.get()
        assert after == before + 1

    def test_fallback_failure_increments_llm_failure_rate_counter_for_fallback(self):
        from src.observability.prometheus_metrics import LLM_FAILURE_RATE

        before = LLM_FAILURE_RATE.labels(provider="vllm-fb")._value.get()
        sel = _make_selector(
            (_make_provider(raises=True), "primary-fb"),
            (_make_provider(raises=True), "vllm-fb"),
            max_failures=99,
        )
        with pytest.raises(LLMUnavailableError):
            sel.complete("q")
        after = LLM_FAILURE_RATE.labels(provider="vllm-fb")._value.get()
        assert after == before + 1

    def test_successful_call_does_not_increment_failure_counter(self):
        from src.observability.prometheus_metrics import LLM_FAILURE_RATE

        before = LLM_FAILURE_RATE.labels(provider="ok-provider")._value.get()
        sel = _make_selector((_make_provider("good"), "ok-provider"))
        sel.complete("q")
        after = LLM_FAILURE_RATE.labels(provider="ok-provider")._value.get()
        assert after == before


# ---------------------------------------------------------------------------
# TestCircuitBreakerState
# ---------------------------------------------------------------------------

class TestCircuitBreakerState:
    def test_circuit_opens_after_five_consecutive_failures(self):
        cb = CircuitBreaker("test-p", max_failures=5)
        for _ in range(5):
            cb.record_failure()
        assert cb.opened_at is not None

    def test_circuit_does_not_open_after_four_failures(self):
        cb = CircuitBreaker("test-p2", max_failures=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.opened_at is None

    def test_circuit_opens_only_after_exactly_five_failures_not_four(self):
        cb = CircuitBreaker("test-p3", max_failures=5)
        for i in range(1, 6):
            cb.record_failure()
            if i < 5:
                assert not cb.is_open(), f"should be closed after {i} failures"
        assert cb.is_open()

    def test_circuit_open_skips_primary_directly_to_fallback(self):
        primary = _make_provider(raises=True)
        fallback = _make_provider("fallback ans")
        sel = _make_selector((primary, "cb-primary"), (fallback, "cb-fallback"), max_failures=1)

        sel.complete("q")  # first call — primary fails, opens circuit after 1 failure
        primary.complete.reset_mock()
        fallback.complete.reset_mock()

        result = sel.complete("q")  # second call — circuit open, primary skipped
        assert result == "fallback ans"
        primary.complete.assert_not_called()

    def test_successful_call_resets_failure_count(self):
        cb = CircuitBreaker("reset-p", max_failures=5)
        for _ in range(3):
            cb.record_failure()
        assert cb.failure_count == 3
        cb.record_success()
        assert cb.failure_count == 0

    def test_circuit_state_gauge_is_1_when_open(self):
        from src.observability.prometheus_metrics import CIRCUIT_BREAKER_STATE

        cb = CircuitBreaker("gauge-open", max_failures=1)
        cb.record_failure()
        assert CIRCUIT_BREAKER_STATE.labels(provider="gauge-open")._value.get() == 1.0

    def test_circuit_state_gauge_is_0_after_success(self):
        from src.observability.prometheus_metrics import CIRCUIT_BREAKER_STATE

        cb = CircuitBreaker("gauge-close", max_failures=1)
        cb.record_failure()  # opens
        cb.record_success()  # closes
        assert CIRCUIT_BREAKER_STATE.labels(provider="gauge-close")._value.get() == 0.0

    def test_is_open_returns_false_when_closed(self):
        cb = CircuitBreaker("fresh", max_failures=5)
        assert cb.is_open() is False

    def test_is_open_returns_true_when_opened(self):
        cb = CircuitBreaker("opened", max_failures=1)
        cb.record_failure()
        assert cb.is_open() is True


# ---------------------------------------------------------------------------
# TestCircuitBreakerTiming
# ---------------------------------------------------------------------------

class TestCircuitBreakerTiming:
    def test_circuit_resets_after_60_seconds(self):
        cb = CircuitBreaker("timing-reset", max_failures=1, open_duration_s=60.0)
        cb.record_failure()
        assert cb.is_open()

        with patch("src.infrastructure.generation.circuit_breaker.time.monotonic") as mock_t:
            mock_t.return_value = cb.opened_at + 61.0
            assert cb.is_open() is False

    def test_circuit_still_open_before_60_seconds_elapsed(self):
        cb = CircuitBreaker("timing-still", max_failures=1, open_duration_s=60.0)
        cb.record_failure()

        with patch("src.infrastructure.generation.circuit_breaker.time.monotonic") as mock_t:
            mock_t.return_value = cb.opened_at + 30.0
            assert cb.is_open() is True

    def test_circuit_resets_failure_count_after_cooldown(self):
        cb = CircuitBreaker("timing-count", max_failures=1, open_duration_s=60.0)
        cb.record_failure()
        opened_at = cb.opened_at

        with patch("src.infrastructure.generation.circuit_breaker.time.monotonic") as mock_t:
            mock_t.return_value = opened_at + 61.0
            cb.is_open()  # triggers half-open reset

        assert cb.failure_count == 0
        assert cb.opened_at is None

    def test_exact_boundary_60_seconds_resets(self):
        cb = CircuitBreaker("timing-exact", max_failures=1, open_duration_s=60.0)
        cb.record_failure()
        opened_at = cb.opened_at

        with patch("src.infrastructure.generation.circuit_breaker.time.monotonic") as mock_t:
            mock_t.return_value = opened_at + 60.0
            assert cb.is_open() is False


# ---------------------------------------------------------------------------
# TestCircuitBreakerIsolation
# ---------------------------------------------------------------------------

class TestCircuitBreakerIsolation:
    def test_multiple_selectors_have_independent_circuits(self):
        p1 = _make_provider(raises=True)
        p2 = _make_provider("ok")
        sel1 = _make_selector((p1, "shared-name"), max_failures=1)
        sel2 = _make_selector((p2, "shared-name"), max_failures=1)

        with pytest.raises(LLMUnavailableError):
            sel1.complete("q")  # opens circuit on sel1

        result = sel2.complete("q")
        assert result == "ok"  # sel2 circuit is independent

    def test_breakers_property_returns_all_provider_names(self):
        sel = _make_selector(
            (_make_provider(), "gemini"),
            (_make_provider(), "vllm"),
        )
        assert set(sel.breakers.keys()) == {"gemini", "vllm"}

    def test_breakers_property_returns_circuit_breaker_instances(self):
        sel = _make_selector((_make_provider(), "only"))
        assert isinstance(sel.breakers["only"], CircuitBreaker)
