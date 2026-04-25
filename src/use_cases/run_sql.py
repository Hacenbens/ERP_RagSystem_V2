"""RunSQLUseCase — application layer thin wrapper around SQLAgent."""
from __future__ import annotations

from src.agents.base_agent import AgentContext
from src.agents.sql_agent import SQLAgent
from src.domain.models.sql_result import SQLResult
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class RunSQLUseCase:
    """Execute the SQL pipeline for a single query."""

    def __init__(self, sql_agent: SQLAgent) -> None:
        self._agent = sql_agent

    async def execute(
        self,
        query: str,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> SQLResult:
        logger.info(
            "run_sql_use_case.start",
            tenant_id=tenant_id,
            erp_module=erp_module,
        )
        context = AgentContext(tenant_id=tenant_id, erp_module=erp_module)
        result = await self._agent.run(query, context)
        logger.info(
            "run_sql_use_case.done",
            row_count=result.row_count,
            tables_used=list(result.tables_used),
        )
        return result


__all__ = ["RunSQLUseCase"]
