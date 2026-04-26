"""
ScoredChunk — a single retrieved document chunk with its relevance score.

Pure domain model — no infrastructure dependencies.
Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 9.1
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoredChunk:
    """A text chunk returned by vector search or reranking, with its relevance score."""

    chunk_id: str
    content: str
    score: float
    source: str
    erp_module: str | None = None


__all__ = ["ScoredChunk"]
