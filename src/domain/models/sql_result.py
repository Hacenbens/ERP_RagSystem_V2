"""
SQLResult — output of the SQLAgent (3-stage pipeline wrapper).

Pure domain model — no infrastructure dependencies.
Maps from ExecutionResult (infrastructure) to this clean domain type.
Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 9.1
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SQLResult:
    """Structured data returned by the SQL pipeline.

    rows is a tuple of dicts to preserve frozen semantics.
    tables_used reflects which ERP tables were queried (for audit).
    """

    query: str
    rows: tuple[dict[str, Any], ...]
    row_count: int
    latency_ms: float
    tables_used: tuple[str, ...] = field(default_factory=tuple)
    query_id: str = ""
    executor: str = "in_memory"
    synthetic: bool = True

    @property
    def success(self) -> bool:
        return True


__all__ = ["SQLResult"]
