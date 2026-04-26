"""RunRAGUseCase — application layer thin wrapper around RAGAgent."""
from __future__ import annotations

from src.agents.base_agent import AgentContext
from src.agents.rag_agent import RAGAgent
from src.domain.models.rag_result import RAGResult
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class RunRAGUseCase:
    """Execute a RAG pipeline for a single query.

    Converts the flat (query, tenant_id, erp_module) call signature expected
    by RouteQueryUseCase into the AgentContext that RAGAgent requires.
    """

    def __init__(self, rag_agent: RAGAgent) -> None:
        self._agent = rag_agent

    async def execute(
        self,
        query: str,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> RAGResult:
        """Run RAG retrieval + generation and return a RAGResult."""
        logger.info(
            "run_rag_use_case.start",
            tenant_id=tenant_id,
            erp_module=erp_module,
        )
        context = AgentContext(tenant_id=tenant_id, erp_module=erp_module)
        result = await self._agent.run(query, context)
        logger.info(
            "run_rag_use_case.done",
            grounded=result.grounded,
            confidence=result.confidence,
        )
        return result


__all__ = ["RunRAGUseCase"]
