"""BaseAgent — abstract base for all Sprint 7+ agents."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Union

from src.domain.models.rag_result import RAGResult
from src.domain.models.sql_result import SQLResult

# Union of all agent output types (HybridResult added in TASK 8)
AgentResult = Union[RAGResult, SQLResult]


@dataclass(frozen=True)
class AgentContext:
    """Per-request context threaded through every agent in the pipeline.

    tenant_id  — mandatory; enforces tenant isolation in vector + SQL queries.
    erp_module — optional; narrows vector search to a specific ERP domain.
    role       — caller's RBAC role; used by SQLAgent for allowed-tables check.
    trace_id   — propagated from the incoming HTTP request for log correlation.
    """

    tenant_id: str
    erp_module: str | None = None
    role: str = "analyst"
    trace_id: str = field(default="")


class BaseAgent(ABC):
    """Minimal contract every agent must satisfy.

    Agents are single-purpose:  they receive a natural-language *query*
    and an *AgentContext*, perform their work, and return an *AgentResult*.
    All agents are async so that HybridAgent can run RAG + SQL in parallel
    via ``asyncio.gather``.
    """

    @abstractmethod
    async def run(self, query: str, context: AgentContext) -> AgentResult:
        """Execute the agent pipeline and return the result."""
        ...


__all__ = ["AgentContext", "AgentResult", "BaseAgent"]
