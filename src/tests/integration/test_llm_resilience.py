"""
Integration tests for the LLM failure path — Sprint 10 (audit findings B-2, B-3).

Sprint 8 shipped ModelSelector, CircuitBreaker and DegradedModeService, and a
live request still returned a bare 500 when the provider failed. Three gaps:

1. ModelSelector caught ConnectionError only, so a 404 for a retired model, a
   401 for a revoked key and a 429 for quota all skipped the fallback,
   left the circuit closed, and propagated.
2. DegradedModeService is not an LLMPort, so nothing could inject it.
3. Classification is the first LLM call in a request, so it failed before any
   agent ran.

These tests pin the behaviour by failure *type*, since the type is what the
old code got wrong.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.agents.query_classifier_agent import QueryClassifierAgent
from src.domain.exceptions import LLMUnavailableError
from src.domain.ports.llm_port import LLMPort
from src.domain.query_intent import QueryIntent
from src.infrastructure.generation.degraded_mode_service import (
    DegradedModeLLM,
    DegradedModeService,
    query_hash,
)
from src.infrastructure.generation.model_selector import ModelSelector
from src.prompts.registry import PromptRegistry

PROMPTS_DIR = "src/prompts"


class _Boom(Exception):
    """A provider-specific error that is not a ConnectionError."""


def _provider(answer: str | None = None, raises: BaseException | None = None) -> MagicMock:
    p = MagicMock(spec=LLMPort)
    if raises is not None:
        p.complete.side_effect = raises
    else:
        p.complete.return_value = answer
    return p


# ---------------------------------------------------------------------------
# B-3 — fallback must trigger on every provider failure, not just transport
# ---------------------------------------------------------------------------

class TestFallbackCoversAllFailureTypes:
    @pytest.mark.parametrize(
        "failure",
        [
            ConnectionError("transport down"),
            _Boom("404 NOT_FOUND: model no longer available to new users"),
            _Boom("401 UNAUTHENTICATED: API key revoked"),
            _Boom("429 RESOURCE_EXHAUSTED: quota exceeded"),
            ValueError("malformed provider response"),
            TimeoutError("read timeout"),
        ],
        ids=["transport", "retired-model", "revoked-key", "rate-limit", "bad-response", "timeout"],
    )
    def test_secondary_provider_answers_when_primary_fails(self, failure):
        """Each of these used to bypass the fallback entirely."""
        primary = _provider(raises=failure)
        secondary = _provider("from-fallback")
        sel = ModelSelector(providers=[(primary, "primary"), (secondary, "secondary")])

        assert sel.complete("q") == "from-fallback"
        secondary.complete.assert_called_once()

    @pytest.mark.parametrize(
        "failure",
        [_Boom("404 model retired"), ValueError("bad"), TimeoutError("slow")],
        ids=["retired-model", "bad-response", "timeout"],
    )
    def test_non_transport_failure_opens_the_circuit(self, failure):
        """A failing provider must be recorded, so the breaker can open."""
        sel = ModelSelector(
            providers=[(_provider(raises=failure), "solo")],
            max_failures=1,
        )
        with pytest.raises(LLMUnavailableError):
            sel.complete("q")

        assert sel.breakers["solo"].is_open() is True

    def test_exhaustion_raises_llm_unavailable_not_the_provider_error(self):
        """Callers depend on one exception type regardless of provider SDK."""
        sel = ModelSelector(providers=[(_provider(raises=_Boom("404")), "p")])
        with pytest.raises(LLMUnavailableError):
            sel.complete("q")


# ---------------------------------------------------------------------------
# B-3 — degraded mode is reachable as an LLMPort
# ---------------------------------------------------------------------------

class TestDegradedModeIsInjectable:
    def test_adapter_is_an_llm_port(self):
        """The reason Sprint 8's degraded mode was never wired."""
        adapter = DegradedModeLLM(DegradedModeService(selector=MagicMock()))
        assert isinstance(adapter, LLMPort)

    def test_outage_returns_the_last_good_answer_for_the_same_prompt(self):
        provider = _provider("the real answer")
        sel = ModelSelector(providers=[(provider, "p")], max_failures=1)
        llm = DegradedModeLLM(DegradedModeService(selector=sel))

        assert llm.complete("same prompt") == "the real answer"

        provider.complete.side_effect = _Boom("404 model retired")
        assert llm.complete("same prompt") == "the real answer"

    def test_outage_with_no_cache_returns_a_degraded_payload_not_an_exception(self):
        sel = ModelSelector(providers=[(_provider(raises=_Boom("404")), "p")])
        llm = DegradedModeLLM(DegradedModeService(selector=sel))

        body = json.loads(llm.complete("never seen before"))
        assert body["degraded"] is True
        assert "unavailable" in body["answer"].lower()

    def test_cache_key_ignores_surrounding_whitespace(self):
        assert query_hash("  a prompt \n") == query_hash("a prompt")


# ---------------------------------------------------------------------------
# B-3 — the classifier is the first LLM call and must not fail the request
# ---------------------------------------------------------------------------

class TestClassifierDegrades:
    @pytest.mark.parametrize(
        "failure",
        [LLMUnavailableError("all providers exhausted"), _Boom("404 model retired")],
        ids=["all-exhausted", "raw-provider-error"],
    )
    def test_classifier_routes_to_hybrid_instead_of_raising(self, failure):
        llm = _provider(raises=failure)
        agent = QueryClassifierAgent(llm=llm, registry=PromptRegistry(PROMPTS_DIR))

        decision = agent.classify("what is our total revenue?")

        assert decision.intent is QueryIntent.HYBRID
        assert "unavailable" in decision.reason.lower()

    def test_fallback_confidence_is_not_blocked_by_the_router(self):
        """RouteQueryUseCase blocks below 0.50; an outage must not read as blocked."""
        llm = _provider(raises=LLMUnavailableError("down"))
        agent = QueryClassifierAgent(llm=llm, registry=PromptRegistry(PROMPTS_DIR))

        assert agent.classify("q").confidence >= 0.50


# ---------------------------------------------------------------------------
# B-2 — the pinned default model must be one that still exists
# ---------------------------------------------------------------------------

class TestGeminiDefaultModel:
    def test_default_is_not_the_retired_model(self):
        """gemini-2.5-flash-lite returns 404 'no longer available to new users'."""
        from src.infrastructure.generation.gemini_llm_client import _DEFAULT_MODEL

        assert _DEFAULT_MODEL != "gemini-2.5-flash-lite"
