"""SQLAgent — wraps the existing 3-stage SQL pipeline.

Pipeline:
  1. QueryGenerator.generate  → GeneratedSQL (NL → raw SQL)
  2. QueryValidator.validate  → ValidationReport (safety + tenant filter check)
  3. QueryExecutor.execute    → ExecutionResult (DB rows)
  4.                          → SQLResult (domain model)

The full RunSQLUseCase (TASK 9) will delegate to this agent.
"""
from __future__ import annotations

from src.agents.base_agent import AgentContext, BaseAgent
from src.domain.models.sql_result import SQLResult
from src.infrastructure.erp.query_executor import QueryExecutor
from src.infrastructure.erp.query_generator import QueryGenerator
from src.infrastructure.erp.query_validator import QueryValidator
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class SQLAgentError(RuntimeError):
    """Raised when the SQL pipeline cannot produce a safe, valid result."""


class SQLAgent(BaseAgent):
    """Drive the 3-stage SQL pipeline and return a ``SQLResult``.

    Raises ``SQLAgentError`` when validation fails so HybridAgent can handle
    partial failure gracefully without catching broad exceptions.
    """

    def __init__(
        self,
        generator: QueryGenerator,
        validator: QueryValidator,
        executor: QueryExecutor,
    ) -> None:
        self._generator = generator
        self._validator = validator
        self._executor = executor

    async def run(self, query: str, context: AgentContext) -> SQLResult:
        """Generate → validate → execute and return a domain SQLResult."""
        logger.info(
            "sql_agent.start",
            tenant_id=context.tenant_id,
            trace_id=context.trace_id,
        )

        generated = self._generator.generate(
            nl_query=query,
            tenant_id=context.tenant_id,
        )

        report = self._validator.validate(generated.raw_sql)
        if not report.can_execute:
            logger.warning(
                "sql_agent.validation_failed",
                errors=report.errors,
                has_tenant_filter=report.has_tenant_filter,
                trace_id=context.trace_id,
            )
            raise SQLAgentError(
                f"SQL validation failed (has_tenant_filter={report.has_tenant_filter}): "
                f"{report.errors}"
            )

        execution = self._executor.execute(report, tenant_id=context.tenant_id)

        result = SQLResult(
            query=execution.sql,
            rows=tuple(execution.rows),
            row_count=execution.row_count,
            latency_ms=execution.latency_ms,
            query_id=execution.query_id,
            executor=execution.executor,
            synthetic=execution.synthetic,
        )

        logger.info(
            "sql_agent.done",
            row_count=result.row_count,
            latency_ms=result.latency_ms,
            trace_id=context.trace_id,
        )
        return result


__all__ = ["SQLAgent", "SQLAgentError"]
