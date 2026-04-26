"""RunHybridUseCase — application layer thin wrapper around HybridAgent."""
from __future__ import annotations

from src.agents.base_agent import AgentContext
from src.agents.hybrid_agent import HybridAgent
from src.domain.models.hybrid_result import HybridResult
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class RunHybridUseCase:
    """Execute RAG + SQL in parallel and return a merged HybridResult."""

    def __init__(self, hybrid_agent: HybridAgent) -> None:
        self._agent = hybrid_agent

    async def execute(
        self,
        query: str,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> HybridResult:
        logger.info(
            "run_hybrid_use_case.start",
            tenant_id=tenant_id,
            erp_module=erp_module,
        )
        context = AgentContext(tenant_id=tenant_id, erp_module=erp_module)
        result = await self._agent.run(query, context)
        logger.info(
            "run_hybrid_use_case.done",
            is_partial=result.is_partial,
            rag_only=result.rag_only,
            sql_only=result.sql_only,
        )
        return result


__all__ = ["RunHybridUseCase"]
