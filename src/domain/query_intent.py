"""
QueryIntent — output of the query classifier.

Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 8.2

The classifier (src/infrastructure/nlp/query_classifier.py) maps every
incoming NL query to one of these four intents, which determines the
pipeline branch that handles the request.

Target classifier accuracy: ≥ 92% (Sprint 9 gate).
"""
from __future__ import annotations

from enum import Enum


class QueryIntent(str, Enum):
    """Four possible routing outcomes for an incoming query."""

    RAG     = "RAG"      # vector search → context builder → LLM
    SQL     = "SQL"      # 3-stage pipeline: generator → validator → executor
    HYBRID  = "HYBRID"   # RAG + SQL in parallel, answers merged
    BLOCKED = "BLOCKED"  # request rejected — harmful or out-of-scope


__all__ = ["QueryIntent"]
