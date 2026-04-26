"""Domain exceptions — centralised error hierarchy for the ERP Agentic RAG system."""
from __future__ import annotations


class ERPRagError(Exception):
    """Base class for all domain exceptions."""


class TenantFilterMissingError(ERPRagError):
    """Raised when a SQL query is missing the mandatory tenant_id filter."""


class LLMUnavailableError(ERPRagError):
    """Raised by ModelSelector when all configured LLM providers have failed.

    The caller (DegradedModeService) catches this and activates the cache
    fallback or returns a degraded-mode response.
    """


class InvalidIntentError(ERPRagError):
    """Raised when the classifier returns an unrecognised intent label."""


__all__ = [
    "ERPRagError",
    "TenantFilterMissingError",
    "LLMUnavailableError",
    "InvalidIntentError",
]
