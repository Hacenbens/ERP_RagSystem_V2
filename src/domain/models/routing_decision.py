"""
RoutingDecision — output of the QueryClassifier agent.

Pure domain model — no infrastructure dependencies.
Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 9.1 + §15.1
"""
from __future__ import annotations

from dataclasses import dataclass

from src.domain.erp_module import ErpModule
from src.domain.query_intent import QueryIntent


@dataclass(frozen=True)
class RoutingDecision:
    """Classification result that drives pipeline routing.

    confidence < 0.50  → BLOCKED (too uncertain)
    confidence < 0.70  → escalate to HYBRID (safe fallback)
    confidence >= 0.70 → trust the classified intent
    """

    intent: QueryIntent
    confidence: float
    erp_module: ErpModule | None
    reason: str


__all__ = ["RoutingDecision"]
