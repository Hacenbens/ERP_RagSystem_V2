from __future__ import annotations

from src.domain.models.scored_chunk import ScoredChunk
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class ContextBuilder:
    """Assemble retrieved chunks into a single LLM-ready context string."""

    def build(self, chunks: list[ScoredChunk], max_tokens: int = 3000) -> str:
        """Build a context window truncated to the approximate token budget."""
        max_chars = max_tokens * 4
        parts: list[str] = []
        total_chars = 0
        used_chunks = 0
        truncated = False

        for chunk in chunks:
            section = (
                f"[{chunk.chunk_id}] (score={chunk.score:.4f}, source={chunk.source})\n"
                f"{chunk.content}\n\n"
            )
            if total_chars + len(section) > max_chars:
                truncated = True
                break
            parts.append(section)
            total_chars += len(section)
            used_chunks += 1

        logger.info(
            "rag.context_builder.done",
            chunks_used=used_chunks,
            total_chars=total_chars,
            truncated=truncated,
            context_utilization=round(total_chars / max_chars, 4) if max_chars else 0.0,
        )
        return "".join(parts)


__all__ = ["ContextBuilder"]
