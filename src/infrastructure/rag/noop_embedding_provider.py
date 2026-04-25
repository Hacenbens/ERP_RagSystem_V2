from __future__ import annotations

from src.domain.ports.embedding_port import EmbeddingPort


class NoopEmbeddingProvider(EmbeddingPort):
    """Test-only embedding provider that returns a fixed-size zero vector."""

    def embed(self, text: str) -> list[float]:
        """Return a deterministic zero vector without calling any external model."""
        return [0.0] * 768


__all__ = ["NoopEmbeddingProvider"]
