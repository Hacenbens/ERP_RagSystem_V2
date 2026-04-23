"""
RAGResult — output of the RAGAgent pipeline.

Pure domain model — no infrastructure dependencies.
Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 9.1
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RAGResult:
    """Answer produced by the RAG pipeline (retrieval + reranking + generation).

    grounded=False means the LLM found no supporting evidence in the context.
    In that case answer is None and the caller should communicate this to the user.
    """

    grounded: bool
    answer: str | None
    cited_chunks: tuple[str, ...]
    grounding_score: float
    confidence: float
    insufficient_data_for: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def not_grounded(cls) -> RAGResult:
        """Convenience constructor for when the LLM finds no supporting context."""
        return cls(
            grounded=False,
            answer=None,
            cited_chunks=(),
            grounding_score=0.0,
            confidence=0.0,
        )


__all__ = ["RAGResult"]
