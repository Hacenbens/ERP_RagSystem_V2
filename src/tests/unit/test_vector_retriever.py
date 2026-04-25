"""
Unit tests for Sprint 7 VectorRetriever and noop embedding provider.
"""
from __future__ import annotations

from src.domain.models.scored_chunk import ScoredChunk
from src.domain.ports.embedding_port import EmbeddingPort
from src.domain.ports.vector_store_port import VectorStorePort
from src.infrastructure.rag.noop_embedding_provider import NoopEmbeddingProvider
from src.infrastructure.rag.vector_retriever import VectorRetriever


class _FakeEmbedder(EmbeddingPort):
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embedding


class _FakeStore(VectorStorePort):
    def __init__(self, results: list[ScoredChunk]) -> None:
        self.results = results
        self.search_calls: list[dict[str, object]] = []

    def has_vectors(self, asset_id: str, tenant_id: str) -> bool:
        return False

    def save_vectors(self, asset_id: str, tenant_id: str, vector_count: int) -> None:
        return None

    def count(self, asset_id: str, tenant_id: str) -> int:
        return 0

    def upsert(
        self,
        asset_id: str,
        tenant_id: str,
        embedding: list[float],
        chunk_id: str,
        content: str,
        erp_module: str | None = None,
    ) -> None:
        return None

    def search_similar(
        self,
        query_embedding: list[float],
        k: int,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> list[ScoredChunk]:
        self.search_calls.append(
            {
                "query_embedding": query_embedding,
                "k": k,
                "tenant_id": tenant_id,
                "erp_module": erp_module,
            }
        )
        return self.results


class TestVectorRetriever:
    def test_retrieve_embeds_query_and_searches_store(self) -> None:
        expected = [
            ScoredChunk(
                chunk_id="chunk-1",
                content="VAT rate guidance",
                score=0.93,
                source="tax-circular.pdf",
                erp_module="finance",
            )
        ]
        embedder = _FakeEmbedder([0.1, 0.2, 0.3])
        store = _FakeStore(expected)
        retriever = VectorRetriever(store=store, embedder=embedder)

        result = retriever.retrieve(
            query="What is the VAT rate?",
            k=5,
            tenant_id="tenant-1",
            erp_module="finance",
        )

        assert result == expected
        assert embedder.calls == ["What is the VAT rate?"]
        assert store.search_calls == [
            {
                "query_embedding": [0.1, 0.2, 0.3],
                "k": 5,
                "tenant_id": "tenant-1",
                "erp_module": "finance",
            }
        ]

    def test_retrieve_passes_none_erp_module(self) -> None:
        embedder = _FakeEmbedder([1.0, 0.0])
        store = _FakeStore([])
        retriever = VectorRetriever(store=store, embedder=embedder)

        result = retriever.retrieve(
            query="List procurement policies",
            k=3,
            tenant_id="tenant-2",
        )

        assert result == []
        assert store.search_calls[0]["erp_module"] is None


class TestNoopEmbeddingProvider:
    def test_embed_returns_768_dimensional_zero_vector(self) -> None:
        provider = NoopEmbeddingProvider()

        vector = provider.embed("ignored input")

        assert len(vector) == 768
        assert set(vector) == {0.0}
