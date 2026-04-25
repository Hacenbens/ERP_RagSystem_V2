"""LLMPort — abstract interface for language model completions."""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMPort(ABC):
    """Generate a text completion for a given prompt.

    Implementations live in ``src/infrastructure/generation/``.
    Tests inject a stub via monkeypatch or a fake subclass.
    """

    @abstractmethod
    def complete(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Return the raw text completion produced by the model."""
        ...


__all__ = ["LLMPort"]
