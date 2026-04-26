"""Integration tests for DegradedModeService (Sprint 8 Task 4).

Tests cover the three outcome paths of DegradedModeService.complete():
  1. Happy path — ModelSelector succeeds; answer cached and returned.
  2. Degraded with cache hit — all providers fail; cached answer returned.
  3. Degraded without cache — all providers fail and no cache; degraded JSON returned.

Additional tests verify:
  - DegradedModePort contract (ABC compliance).
  - DEGRADED_MODE_ACTIVATIONS counter increments.
  - Logging structured events.
  - Cache injection and isolation.
  - Multiple calls accumulate in cache.
  - Cache is not written on LLMUnavailableError.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.domain.exceptions import LLMUnavailableError
from src.domain.ports.degraded_mode_port import DegradedModePort
from src.infrastructure.generation.degraded_mode_service import (
    DegradedModeService,
    _UNAVAILABLE_RESPONSE,
)
from src.infrastructure.generation.model_selector import ModelSelector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_selector(answer: str | None = None, raises: bool = False) -> MagicMock:
    """Return a MagicMock ModelSelector whose complete() either returns *answer* or raises."""
    mock = MagicMock(spec=ModelSelector)
    if raises:
        mock.complete.side_effect = LLMUnavailableError("all providers down")
    else:
        mock.complete.return_value = answer or "hello from LLM"
    return mock


# ---------------------------------------------------------------------------
# ABC / contract
# ---------------------------------------------------------------------------

class TestDegradedModePortContract:
    def test_is_subclass_of_degraded_mode_port(self):
        selector = _make_selector()
        svc = DegradedModeService(selector)
        assert isinstance(svc, DegradedModePort)

    def test_has_complete_method(self):
        svc = DegradedModeService(_make_selector())
        assert callable(svc.complete)

    def test_has_get_cached_method(self):
        svc = DegradedModeService(_make_selector())
        assert callable(svc.get_cached)

    def test_has_set_cached_method(self):
        svc = DegradedModeService(_make_selector())
        assert callable(svc.set_cached)


# ---------------------------------------------------------------------------
# Happy path — LLM succeeds
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_llm_answer(self):
        svc = DegradedModeService(_make_selector("the answer"))
        result = svc.complete("what is 2+2?", "hash-001")
        assert result == "the answer"

    def test_caches_answer_after_success(self):
        svc = DegradedModeService(_make_selector("cached value"))
        svc.complete("prompt", "hash-002")
        assert svc.get_cached("hash-002") == "cached value"

    def test_selector_called_with_prompt(self):
        mock_selector = _make_selector("ok")
        svc = DegradedModeService(mock_selector)
        svc.complete("my prompt", "hash-003")
        mock_selector.complete.assert_called_once_with("my prompt")

    def test_multiple_calls_cache_independently(self):
        mock_selector = MagicMock(spec=ModelSelector)
        mock_selector.complete.side_effect = ["answer-A", "answer-B"]
        svc = DegradedModeService(mock_selector)
        svc.complete("q1", "hash-A")
        svc.complete("q2", "hash-B")
        assert svc.get_cached("hash-A") == "answer-A"
        assert svc.get_cached("hash-B") == "answer-B"

    def test_same_hash_overwrites_cache(self):
        mock_selector = MagicMock(spec=ModelSelector)
        mock_selector.complete.side_effect = ["first", "second"]
        svc = DegradedModeService(mock_selector)
        svc.complete("p1", "same-hash")
        svc.complete("p2", "same-hash")
        assert svc.get_cached("same-hash") == "second"


# ---------------------------------------------------------------------------
# Degraded with cache hit
# ---------------------------------------------------------------------------

class TestDegradedWithCache:
    def test_returns_cached_answer_when_llm_fails(self):
        svc = DegradedModeService(_make_selector(raises=True), cache={"hash-X": "stale answer"})
        result = svc.complete("prompt", "hash-X")
        assert result == "stale answer"

    def test_cache_not_overwritten_on_failure(self):
        svc = DegradedModeService(_make_selector(raises=True), cache={"hash-Y": "original"})
        svc.complete("prompt", "hash-Y")
        assert svc.get_cached("hash-Y") == "original"

    def test_different_hash_returns_none_not_cached(self):
        svc = DegradedModeService(_make_selector(raises=True), cache={"hash-Z": "stored"})
        result = svc.complete("prompt", "hash-MISS")
        parsed = json.loads(result)
        assert parsed["degraded"] is True


# ---------------------------------------------------------------------------
# Degraded without cache
# ---------------------------------------------------------------------------

class TestDegradedWithoutCache:
    def test_returns_degraded_json_string(self):
        svc = DegradedModeService(_make_selector(raises=True))
        result = svc.complete("prompt", "hash-no-cache")
        assert result == _UNAVAILABLE_RESPONSE

    def test_degraded_json_is_valid_json(self):
        svc = DegradedModeService(_make_selector(raises=True))
        result = svc.complete("prompt", "new-hash")
        parsed = json.loads(result)
        assert parsed["degraded"] is True
        assert parsed["cached_answer"] is None
        assert "unavailable" in parsed["answer"].lower()

    def test_degraded_json_has_required_keys(self):
        svc = DegradedModeService(_make_selector(raises=True))
        result = svc.complete("any prompt", "any-hash")
        parsed = json.loads(result)
        assert "degraded" in parsed
        assert "cached_answer" in parsed
        assert "answer" in parsed

    def test_no_cache_entry_created_on_failure(self):
        svc = DegradedModeService(_make_selector(raises=True))
        svc.complete("prompt", "empty-hash")
        assert svc.get_cached("empty-hash") is None


# ---------------------------------------------------------------------------
# Prometheus counter
# ---------------------------------------------------------------------------

class TestPrometheusCounter:
    def test_activations_incremented_on_llm_failure(self):
        from src.observability.prometheus_metrics import DEGRADED_MODE_ACTIVATIONS

        before = DEGRADED_MODE_ACTIVATIONS._value.get()
        svc = DegradedModeService(_make_selector(raises=True))
        svc.complete("prompt", "counter-hash")
        after = DEGRADED_MODE_ACTIVATIONS._value.get()
        assert after == before + 1

    def test_activations_not_incremented_on_success(self):
        from src.observability.prometheus_metrics import DEGRADED_MODE_ACTIVATIONS

        before = DEGRADED_MODE_ACTIVATIONS._value.get()
        svc = DegradedModeService(_make_selector("ok"))
        svc.complete("prompt", "no-inc-hash")
        after = DEGRADED_MODE_ACTIVATIONS._value.get()
        assert after == before

    def test_activations_incremented_per_failure(self):
        from src.observability.prometheus_metrics import DEGRADED_MODE_ACTIVATIONS

        before = DEGRADED_MODE_ACTIVATIONS._value.get()
        svc = DegradedModeService(_make_selector(raises=True))
        svc.complete("p", "h1")
        svc.complete("p", "h2")
        after = DEGRADED_MODE_ACTIVATIONS._value.get()
        assert after == before + 2


# ---------------------------------------------------------------------------
# Cache injection
# ---------------------------------------------------------------------------

class TestCacheInjection:
    def test_pre_seeded_cache_used_for_hit(self):
        pre_seeded = {"pre-hash": "pre-answer"}
        svc = DegradedModeService(_make_selector(raises=True), cache=pre_seeded)
        result = svc.complete("ignored", "pre-hash")
        assert result == "pre-answer"

    def test_default_cache_is_empty_dict(self):
        svc = DegradedModeService(_make_selector())
        assert svc.get_cached("anything") is None

    def test_cache_mutated_in_place(self):
        cache = {}
        svc = DegradedModeService(_make_selector("written"), cache=cache)
        svc.complete("q", "mut-hash")
        assert cache["mut-hash"] == "written"

    def test_two_instances_do_not_share_cache(self):
        svc1 = DegradedModeService(_make_selector("a"))
        svc2 = DegradedModeService(_make_selector("b"))
        svc1.complete("q", "shared-hash")
        assert svc2.get_cached("shared-hash") is None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogging:
    def test_degraded_event_logged_on_failure(self):
        svc = DegradedModeService(_make_selector(raises=True))
        with patch("src.infrastructure.generation.degraded_mode_service.logger") as mock_log:
            svc.complete("prompt", "log-hash")
            mock_log.warning.assert_called_once()
            call_kwargs = mock_log.warning.call_args
            assert call_kwargs[0][0] == "degraded_mode.activated"

    def test_degraded_log_includes_cache_hit_false(self):
        svc = DegradedModeService(_make_selector(raises=True))
        with patch("src.infrastructure.generation.degraded_mode_service.logger") as mock_log:
            svc.complete("prompt", "no-cache-hash")
            _, kwargs = mock_log.warning.call_args
            assert kwargs.get("cache_hit") is False

    def test_degraded_log_includes_cache_hit_true(self):
        svc = DegradedModeService(_make_selector(raises=True), cache={"log-hit-hash": "old"})
        with patch("src.infrastructure.generation.degraded_mode_service.logger") as mock_log:
            svc.complete("prompt", "log-hit-hash")
            _, kwargs = mock_log.warning.call_args
            assert kwargs.get("cache_hit") is True

    def test_no_warning_logged_on_success(self):
        svc = DegradedModeService(_make_selector("ok"))
        with patch("src.infrastructure.generation.degraded_mode_service.logger") as mock_log:
            svc.complete("prompt", "success-hash")
            mock_log.warning.assert_not_called()
