"""
Unit tests for Sprint 7 VectorStorePort extensions.

Covers: InMemoryVectorStore.upsert / search_similar / clear
        MongoVectorStore.upsert / search_similar raise NotImplementedError
"""
from __future__ import annotations

import math

import pytest

from src.domain.models.scored_chunk import ScoredChunk
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.infrastructure.vector_store.mongo_vector_store import MongoVectorStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit(dim: int, axis: int) -> list[float]:
    """Return a unit vector of length *dim* pointing along *axis*."""
    v = [0.0] * dim
    v[axis] = 1.0
    return v


# ---------------------------------------------------------------------------
# InMemoryVectorStore — upsert
# ---------------------------------------------------------------------------

class TestInMemoryUpsert:
    def setup_method(self) -> None:
        self.store = InMemoryVectorStore()

    def test_upsert_stores_chunk(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-1", "VAT is 9%")
        results = self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-1")
        assert len(results) == 1
        assert results[0].chunk_id == "c-1"

    def test_upsert_is_idempotent(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-1", "first version")
        self.store.upsert("a-1", "t-1", _unit(3, 1), "c-1", "second version")
        results = self.store.search_similar(_unit(3, 1), k=5, tenant_id="t-1")
        assert len(results) == 1
        assert results[0].content == "second version"

    def test_upsert_stores_erp_module(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-1", "text", erp_module="finance")
        results = self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-1")
        assert results[0].erp_module == "finance"

    def test_upsert_erp_module_optional(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-1", "text")
        results = self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-1")
        assert results[0].erp_module is None


# ---------------------------------------------------------------------------
# InMemoryVectorStore — search_similar
# ---------------------------------------------------------------------------

class TestInMemorySearchSimilar:
    def setup_method(self) -> None:
        self.store = InMemoryVectorStore()

    def test_returns_scored_chunks(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-1", "content A")
        results = self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-1")
        assert isinstance(results[0], ScoredChunk)

    def test_score_is_cosine_similarity(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-1", "text")
        results = self.store.search_similar(_unit(3, 0), k=1, tenant_id="t-1")
        assert math.isclose(results[0].score, 1.0, abs_tol=1e-9)

    def test_results_ordered_descending(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-best", "most similar")
        self.store.upsert("a-1", "t-1", _unit(3, 1), "c-worst", "orthogonal")
        query = _unit(3, 0)
        results = self.store.search_similar(query, k=5, tenant_id="t-1")
        assert results[0].chunk_id == "c-best"
        assert results[0].score >= results[1].score

    def test_k_limits_results(self) -> None:
        for i in range(5):
            self.store.upsert("a-1", "t-1", _unit(5, i), f"c-{i}", f"chunk {i}")
        results = self.store.search_similar(_unit(5, 0), k=2, tenant_id="t-1")
        assert len(results) == 2

    def test_tenant_scoping(self) -> None:
        self.store.upsert("a-1", "t-A", _unit(3, 0), "c-A", "tenant A chunk")
        self.store.upsert("a-1", "t-B", _unit(3, 0), "c-B", "tenant B chunk")
        results = self.store.search_similar(_unit(3, 0), k=10, tenant_id="t-A")
        chunk_ids = {r.chunk_id for r in results}
        assert "c-A" in chunk_ids
        assert "c-B" not in chunk_ids

    def test_erp_module_filter(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-fin", "finance chunk", erp_module="finance")
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-hr", "HR chunk", erp_module="hr")
        results = self.store.search_similar(_unit(3, 0), k=10, tenant_id="t-1", erp_module="finance")
        chunk_ids = {r.chunk_id for r in results}
        assert "c-fin" in chunk_ids
        assert "c-hr" not in chunk_ids

    def test_no_erp_module_filter_returns_all(self) -> None:
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-fin", "finance", erp_module="finance")
        self.store.upsert("a-1", "t-1", _unit(3, 0), "c-hr", "HR", erp_module="hr")
        results = self.store.search_similar(_unit(3, 0), k=10, tenant_id="t-1")
        assert len(results) == 2

    def test_empty_store_returns_empty_list(self) -> None:
        results = self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-1")
        assert results == []

    def test_zero_vector_returns_zero_score(self) -> None:
        self.store.upsert("a-1", "t-1", [0.0, 0.0, 0.0], "c-zero", "zero vec")
        results = self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-1")
        assert results[0].score == 0.0

    def test_source_is_asset_id(self) -> None:
        self.store.upsert("asset-42", "t-1", _unit(3, 0), "c-1", "text")
        results = self.store.search_similar(_unit(3, 0), k=1, tenant_id="t-1")
        assert results[0].source == "asset-42"


# ---------------------------------------------------------------------------
# InMemoryVectorStore — clear also wipes vectors
# ---------------------------------------------------------------------------

class TestInMemoryClear:
    def test_clear_removes_vectors(self) -> None:
        store = InMemoryVectorStore()
        store.upsert("a-1", "t-1", _unit(3, 0), "c-1", "text")
        store.clear()
        assert store.search_similar(_unit(3, 0), k=5, tenant_id="t-1") == []

    def test_clear_removes_idempotency_store(self) -> None:
        store = InMemoryVectorStore()
        store.save_vectors("a-1", "t-1", 10)
        store.clear()
        assert not store.has_vectors("a-1", "t-1")


# ---------------------------------------------------------------------------
# MongoVectorStore — Sprint 7 stubs
# ---------------------------------------------------------------------------

class TestMongoVectorStoreStubs:
    def setup_method(self) -> None:
        self.store = MongoVectorStore(collection=None)

    def test_upsert_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="Sprint 8"):
            self.store.upsert("a-1", "t-1", _unit(3, 0), "c-1", "text")

    def test_search_similar_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="Sprint 8"):
            self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-1")
