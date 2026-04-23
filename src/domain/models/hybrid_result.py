"""
HybridResult — output of the HybridAgent (RAG + SQL merged).

Pure domain model — no infrastructure dependencies.
Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 9.1
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.models.rag_result import RAGResult
from src.domain.models.sql_result import SQLResult


@dataclass(frozen=True)
class HybridResult:
    """Combined answer from parallel RAG + SQL execution.

    Partial failure cases:
      rag_only=True  → SQL agent failed; answer derived from RAG alone
      sql_only=True  → RAG agent failed; answer derived from SQL alone
    When both succeed, merged_answer holds the LLM-synthesised response.
    When both fail, HybridAgent raises HybridAgentError — this model is never created.
    """

    rag_result: RAGResult | None
    sql_result: SQLResult | None
    merged_answer: str | None
    sql_contribution: str
    rag_contribution: str
    overall_confidence: float
    contradictions: tuple[str, ...] = field(default_factory=tuple)
    cited_chunks: tuple[str, ...] = field(default_factory=tuple)
    sql_tables_used: tuple[str, ...] = field(default_factory=tuple)
    rag_only: bool = False
    sql_only: bool = False

    @property
    def is_partial(self) -> bool:
        return self.rag_only or self.sql_only

    @classmethod
    def rag_fallback(cls, rag_result: RAGResult) -> HybridResult:
        """Partial result when SQL agent failed — RAG answer only."""
        return cls(
            rag_result=rag_result,
            sql_result=None,
            merged_answer=None,
            sql_contribution="",
            rag_contribution="SQL agent unavailable — answer from documents only.",
            overall_confidence=rag_result.confidence,
            rag_only=True,
        )

    @classmethod
    def sql_fallback(cls, sql_result: SQLResult) -> HybridResult:
        """Partial result when RAG agent failed — SQL answer only."""
        return cls(
            rag_result=None,
            sql_result=sql_result,
            merged_answer=None,
            sql_contribution="RAG agent unavailable — answer from structured data only.",
            rag_contribution="",
            overall_confidence=1.0 if sql_result.row_count > 0 else 0.5,
            sql_only=True,
        )


__all__ = ["HybridResult"]
