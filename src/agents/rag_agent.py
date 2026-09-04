"""RAGAgent — retrieval-augmented generation pipeline.

Pipeline:
  1. VectorRetriever  → top-K candidate chunks (default k=20)
  2. Reranker         → top-5 cross-encoder-scored chunks
  3. ContextBuilder   → token-budgeted context string
  4. LLMPort.complete → JSON answer
  5. PromptRegistry.validate_output → schema check
  6.                  → RAGResult
"""
from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from src.agents.base_agent import AgentContext, BaseAgent
from src.agents.helpers import parse_llm_json
from src.domain.models.rag_result import RAGResult
from src.domain.ports.llm_port import LLMPort
from src.infrastructure.rag.context_builder import ContextBuilder
from src.infrastructure.rag.vector_retriever import VectorRetriever
from src.observability.structured_logger import get_logger
from src.prompts.registry import PromptRegistry

logger = get_logger(__name__)

_EACH_BLOCK_RE = re.compile(
    r"\{\{#each chunks\}\}.*?\{\{/each\}\}", re.DOTALL
)


@runtime_checkable
class _Reranker(Protocol):
    """Structural protocol — accepts IdentityReranker or CrossEncoderReranker."""

    def rerank(self, query: str, docs: list, top_k: int) -> list: ...


def _render_prompt(prompt_text: str, query: str, context_str: str) -> str:
    """Replace the {{#each chunks}}...{{/each}} block and {{masked_query}}."""
    rendered = _EACH_BLOCK_RE.sub(context_str.rstrip("\n"), prompt_text)
    return rendered.replace("{{masked_query}}", query)


class RAGAgent(BaseAgent):
    """Execute the full RAG pipeline for a user query.

    Resolves the ``rag_answer`` production prompt, calls the LLM, validates
    the JSON output against the registered schema, and returns a ``RAGResult``.
    Falls back to ``RAGResult.not_grounded()`` on JSON parse or schema errors.
    """

    def __init__(
        self,
        retriever: VectorRetriever,
        reranker: _Reranker,
        context_builder: ContextBuilder,
        llm: LLMPort,
        registry: PromptRegistry,
        retrieve_k: int = 20,
        rerank_top_k: int = 5,
        context_max_tokens: int = 3000,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._context_builder = context_builder
        self._llm = llm
        self._registry = registry
        self._retrieve_k = retrieve_k
        self._rerank_top_k = rerank_top_k
        self._context_max_tokens = context_max_tokens

    async def run(self, query: str, context: AgentContext) -> RAGResult:
        """Run retrieve → rerank → build-context → generate → parse."""
        logger.info(
            "rag_agent.start",
            tenant_id=context.tenant_id,
            erp_module=context.erp_module,
            trace_id=context.trace_id,
        )

        chunks = self._retriever.retrieve(
            query,
            k=self._retrieve_k,
            tenant_id=context.tenant_id,
            erp_module=context.erp_module,
        )
        ranked = self._reranker.rerank(query, chunks, top_k=self._rerank_top_k)
        context_str = self._context_builder.build(ranked, max_tokens=self._context_max_tokens)

        pv = self._registry.resolve("rag_answer")
        prompt = _render_prompt(pv.prompt_text, query, context_str)

        raw = self._llm.complete(
            prompt,
            temperature=pv.parameters.temperature,
            max_tokens=pv.parameters.max_tokens,
        )

        try:
            output: dict[str, Any] = parse_llm_json(raw)
            self._registry.validate_output(pv, output)
        except Exception as exc:
            logger.warning("rag_agent.parse_failed", error=str(exc))
            return RAGResult.not_grounded()

        result = RAGResult(
            grounded=output["grounded"],
            answer=output["answer"],
            cited_chunks=tuple(output.get("cited_chunks", [])),
            grounding_score=float(output["confidence"]),
            confidence=float(output["confidence"]),
            insufficient_data_for=tuple(output.get("insufficient_data_for", [])),
        )

        logger.info(
            "rag_agent.done",
            grounded=result.grounded,
            confidence=result.confidence,
            cited_chunks=len(result.cited_chunks),
            trace_id=context.trace_id,
        )
        return result


__all__ = ["RAGAgent"]
