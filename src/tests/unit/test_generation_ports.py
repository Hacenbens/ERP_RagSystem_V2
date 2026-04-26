"""
Unit tests — Sprint 8 Task 1: ModelSelectorPort, DegradedModePort, domain exceptions.

Covers all acceptance criteria:
  - ModelSelectorPort is a pure ABC with .complete() abstract
  - DegradedModePort is a pure ABC with .get_cached() and .set_cached() abstract
  - Concrete subclasses missing abstract methods cannot be instantiated (TypeError)
  - Concrete subclasses implementing all methods instantiate and work correctly
  - Exception hierarchy: LLMUnavailableError, TenantFilterMissingError,
    InvalidIntentError all inherit from ERPRagError → Exception
  - All symbols are importable from src.domain.ports and their own modules
  - Method signatures carry correct type annotations

Naming: test_{subject}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

import inspect

import pytest

from src.domain.exceptions import (
    ERPRagError,
    InvalidIntentError,
    LLMUnavailableError,
    TenantFilterMissingError,
)
from src.domain.ports import DegradedModePort, ModelSelectorPort
from src.domain.ports.degraded_mode_port import DegradedModePort as _DegradedModePortDirect
from src.domain.ports.model_selector_port import ModelSelectorPort as _ModelSelectorPortDirect


# ---------------------------------------------------------------------------
# Minimal concrete implementations used by the tests
# ---------------------------------------------------------------------------

class _ConcreteSelector(ModelSelectorPort):
    """Minimal implementation that returns a fixed answer."""

    def complete(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        return f"answer::{prompt[:10]}"


class _ConcreteCache(DegradedModePort):
    """Minimal implementation backed by an in-memory dict."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_cached(self, query_hash: str) -> str | None:
        return self._store.get(query_hash)

    def set_cached(self, query_hash: str, answer: str) -> None:
        self._store[query_hash] = answer


# ---------------------------------------------------------------------------
# ABC enforcement — ModelSelectorPort
# ---------------------------------------------------------------------------

class TestModelSelectorPortIsABC:
    """ModelSelectorPort must be uninstantiable and enforce complete()."""

    def test_model_selector_port_cannot_be_instantiated_directly(self):
        with pytest.raises(TypeError):
            ModelSelectorPort()  # type: ignore[abstract]

    def test_model_selector_port_subclass_missing_complete_cannot_be_instantiated(self):
        class _Incomplete(ModelSelectorPort):
            pass  # complete() not implemented

        with pytest.raises(TypeError):
            _Incomplete()

    def test_model_selector_port_complete_is_in_abstract_methods(self):
        assert "complete" in ModelSelectorPort.__abstractmethods__

    def test_model_selector_port_has_exactly_one_abstract_method(self):
        assert len(ModelSelectorPort.__abstractmethods__) == 1

    def test_concrete_selector_with_complete_instantiates(self):
        selector = _ConcreteSelector()
        assert isinstance(selector, ModelSelectorPort)

    def test_concrete_selector_complete_returns_string(self):
        selector = _ConcreteSelector()
        result = selector.complete("What is the VAT rate?")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_concrete_selector_complete_accepts_temperature_kwarg(self):
        selector = _ConcreteSelector()
        result = selector.complete("prompt", temperature=0.7)
        assert isinstance(result, str)

    def test_concrete_selector_complete_accepts_max_tokens_kwarg(self):
        selector = _ConcreteSelector()
        result = selector.complete("prompt", max_tokens=1024)
        assert isinstance(result, str)

    def test_concrete_selector_complete_default_temperature_is_zero(self):
        sig = inspect.signature(ModelSelectorPort.complete)
        assert sig.parameters["temperature"].default == 0.0

    def test_concrete_selector_complete_default_max_tokens_is_512(self):
        sig = inspect.signature(ModelSelectorPort.complete)
        assert sig.parameters["max_tokens"].default == 512


# ---------------------------------------------------------------------------
# ABC enforcement — DegradedModePort
# ---------------------------------------------------------------------------

class TestDegradedModePortIsABC:
    """DegradedModePort must enforce both get_cached() and set_cached()."""

    def test_degraded_mode_port_cannot_be_instantiated_directly(self):
        with pytest.raises(TypeError):
            DegradedModePort()  # type: ignore[abstract]

    def test_degraded_mode_port_subclass_missing_both_methods_cannot_instantiate(self):
        class _Empty(DegradedModePort):
            pass

        with pytest.raises(TypeError):
            _Empty()

    def test_degraded_mode_port_subclass_missing_set_cached_cannot_instantiate(self):
        class _OnlyGet(DegradedModePort):
            def get_cached(self, query_hash: str) -> str | None:
                return None

        with pytest.raises(TypeError):
            _OnlyGet()

    def test_degraded_mode_port_subclass_missing_get_cached_cannot_instantiate(self):
        class _OnlySet(DegradedModePort):
            def set_cached(self, query_hash: str, answer: str) -> None:
                pass

        with pytest.raises(TypeError):
            _OnlySet()

    def test_degraded_mode_port_has_two_abstract_methods(self):
        assert DegradedModePort.__abstractmethods__ == frozenset(
            {"get_cached", "set_cached"}
        )

    def test_concrete_cache_instantiates(self):
        cache = _ConcreteCache()
        assert isinstance(cache, DegradedModePort)

    def test_concrete_cache_get_returns_none_for_unknown_hash(self):
        cache = _ConcreteCache()
        assert cache.get_cached("unknown-hash") is None

    def test_concrete_cache_set_then_get_returns_stored_answer(self):
        cache = _ConcreteCache()
        cache.set_cached("hash-abc", "the answer")
        assert cache.get_cached("hash-abc") == "the answer"

    def test_concrete_cache_set_overwrites_existing_entry(self):
        cache = _ConcreteCache()
        cache.set_cached("h1", "first")
        cache.set_cached("h1", "second")
        assert cache.get_cached("h1") == "second"

    def test_concrete_cache_different_hashes_are_independent(self):
        cache = _ConcreteCache()
        cache.set_cached("h1", "answer-one")
        cache.set_cached("h2", "answer-two")
        assert cache.get_cached("h1") == "answer-one"
        assert cache.get_cached("h2") == "answer-two"

    def test_concrete_cache_get_returns_none_after_different_hash_set(self):
        cache = _ConcreteCache()
        cache.set_cached("h1", "value")
        assert cache.get_cached("h2") is None


# ---------------------------------------------------------------------------
# Method signatures — DegradedModePort
# ---------------------------------------------------------------------------

class TestDegradedModePortSignatures:

    def test_get_cached_first_parameter_is_query_hash(self):
        params = list(inspect.signature(DegradedModePort.get_cached).parameters)
        assert params[1] == "query_hash"

    def test_set_cached_parameters_are_query_hash_and_answer(self):
        params = list(inspect.signature(DegradedModePort.set_cached).parameters)
        assert params[1] == "query_hash"
        assert params[2] == "answer"

    def test_set_cached_return_annotation_is_none(self):
        sig = inspect.signature(DegradedModePort.set_cached)
        # With `from __future__ import annotations` annotations are stored as strings
        assert sig.return_annotation in (None, type(None), "None", inspect.Parameter.empty)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class TestDomainExceptionHierarchy:
    """All domain exceptions must descend from ERPRagError → Exception."""

    def test_erp_rag_error_is_exception(self):
        assert issubclass(ERPRagError, Exception)

    def test_llm_unavailable_error_is_erp_rag_error(self):
        assert issubclass(LLMUnavailableError, ERPRagError)

    def test_tenant_filter_missing_error_is_erp_rag_error(self):
        assert issubclass(TenantFilterMissingError, ERPRagError)

    def test_invalid_intent_error_is_erp_rag_error(self):
        assert issubclass(InvalidIntentError, ERPRagError)

    def test_llm_unavailable_error_is_catchable_as_exception(self):
        with pytest.raises(Exception):
            raise LLMUnavailableError("all providers exhausted")

    def test_tenant_filter_missing_error_is_catchable_as_erp_rag_error(self):
        with pytest.raises(ERPRagError):
            raise TenantFilterMissingError("no tenant_id filter in SQL")

    def test_invalid_intent_error_is_catchable_as_erp_rag_error(self):
        with pytest.raises(ERPRagError):
            raise InvalidIntentError("unknown intent: UNKNOWN")

    def test_llm_unavailable_error_carries_message(self):
        err = LLMUnavailableError("openai and vllm both failed")
        assert "openai" in str(err)

    def test_tenant_filter_missing_error_carries_message(self):
        err = TenantFilterMissingError("has_tenant_filter=False")
        assert "has_tenant_filter" in str(err)

    def test_invalid_intent_error_carries_message(self):
        err = InvalidIntentError("GARBAGE")
        assert "GARBAGE" in str(err)

    def test_domain_exceptions_are_independent_subtypes(self):
        """LLMUnavailableError must NOT catch TenantFilterMissingError."""
        with pytest.raises(TenantFilterMissingError):
            try:
                raise TenantFilterMissingError("missing filter")
            except LLMUnavailableError:
                pass  # must not be caught here

    def test_erp_rag_error_catches_all_domain_exceptions(self):
        for exc_class in (
            LLMUnavailableError,
            TenantFilterMissingError,
            InvalidIntentError,
        ):
            with pytest.raises(ERPRagError):
                raise exc_class("test message")


# ---------------------------------------------------------------------------
# Public API — importability and __all__
# ---------------------------------------------------------------------------

class TestPublicAPI:
    """All symbols must be importable from both their module and src.domain.ports."""

    def test_model_selector_port_importable_from_own_module(self):
        assert _ModelSelectorPortDirect is ModelSelectorPort

    def test_degraded_mode_port_importable_from_own_module(self):
        assert _DegradedModePortDirect is DegradedModePort

    def test_model_selector_port_importable_from_domain_ports_package(self):
        from src.domain.ports import ModelSelectorPort as _M
        assert _M is ModelSelectorPort

    def test_degraded_mode_port_importable_from_domain_ports_package(self):
        from src.domain.ports import DegradedModePort as _D
        assert _D is DegradedModePort

    def test_model_selector_port_in_module_all(self):
        import src.domain.ports.model_selector_port as m
        assert "ModelSelectorPort" in m.__all__

    def test_degraded_mode_port_in_module_all(self):
        import src.domain.ports.degraded_mode_port as m
        assert "DegradedModePort" in m.__all__

    def test_all_exception_symbols_in_exceptions_all(self):
        import src.domain.exceptions as m
        for name in ("ERPRagError", "LLMUnavailableError",
                     "TenantFilterMissingError", "InvalidIntentError"):
            assert name in m.__all__, f"{name} missing from exceptions.__all__"

    def test_model_selector_port_in_domain_ports_init_all(self):
        import src.domain.ports as pkg
        assert "ModelSelectorPort" in pkg.__all__

    def test_degraded_mode_port_in_domain_ports_init_all(self):
        import src.domain.ports as pkg
        assert "DegradedModePort" in pkg.__all__
