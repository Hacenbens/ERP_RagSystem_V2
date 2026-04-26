"""
Port: EmbeddingPort

Abstract interface for text embedding providers used by the RAG pipeline.
Infrastructure implementations live in src/infrastructure/rag/ or later NLP
providers wired through DI.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingPort(ABC):
    """Generate a dense vector embedding for a text input."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return a vector embedding for *text*."""


__all__ = ["EmbeddingPort"]
