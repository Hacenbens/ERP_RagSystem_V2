from __future__ import annotations

from src.domain.models.scored_chunk import ScoredChunk
from src.domain.ports.embedding_port import EmbeddingPort
from src.domain.ports.vector_store_port import VectorStorePort
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
        """Embed the query and return the top-k most similar chunks."""
        logger.info(
            "rag.retriever.start",
            tenant_id=tenant_id,
            erp_module=erp_module,
            k=k,
        )
        embedding = self._embedder.embed(query)
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
        )
        return chunks


__all__ = ["VectorRetriever"]
