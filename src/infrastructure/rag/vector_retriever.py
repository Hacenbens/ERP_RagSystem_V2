from __future__ import annotations

from src.domain.exceptions import EmbeddingUnavailableError
from src.domain.models.scored_chunk import ScoredChunk
from src.domain.ports.embedding_port import EmbeddingPort
from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.stage_timer import Stage, stage_timer
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class VectorRetriever:
    """Retrieve the most relevant chunks for a user query."""

    def __init__(self, store: VectorStorePort, embedder: EmbeddingPort) -> None:
        """Bind the vector store and embedding provider used for retrieval."""
        self._store = store
        self._embedder = embedder

    def retrieve(
        self,
        query: str,
        k: int,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> list[ScoredChunk]:
        """Embed the query and return the top-k most similar chunks.

        Returns an empty list when embedding is unavailable. The RAG branch
        then produces an ungrounded answer, and HybridAgent still has its SQL
        half — whereas an exception here reached the route as a 500 on every
        RAG query, which is what a dead embedding tunnel actually did.
        """
        logger.info(
            "rag.retriever.start",
            tenant_id=tenant_id,
            erp_module=erp_module,
            k=k,
        )
        with stage_timer(Stage.RETRIEVE) as timing:
            try:
                embedding = self._embedder.embed(query)
            except EmbeddingUnavailableError as exc:
                logger.error(
                    "rag.retriever.embedding_unavailable",
                    tenant_id=tenant_id,
                    erp_module=erp_module,
                    error=str(exc),
                )
                return []
            chunks = self._store.search_similar(
                query_embedding=embedding,
                k=k,
                tenant_id=tenant_id,
                erp_module=erp_module,
            )
        logger.info(
            "rag.retriever.done",
            tenant_id=tenant_id,
            erp_module=erp_module,
            chunk_count=len(chunks),
            latency_ms=round(timing.elapsed_ms, 2),
        )
        return chunks


__all__ = ["VectorRetriever"]
