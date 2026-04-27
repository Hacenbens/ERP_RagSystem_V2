"""
Unit tests for Sprint 7 VectorStorePort extensions.

Covers: InMemoryVectorStore.upsert / search_similar / clear
        MongoVectorStore.upsert / search_similar raise NotImplementedError
        MilvusVectorStore — full port compliance (Sprint 9 Task 2)
"""
from __future__ import annotations

import math

import pytest

from src.domain.models.scored_chunk import ScoredChunk
from src.domain.ports.vector_store_port import VectorStorePort
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.infrastructure.vector_store.milvus_vector_store import MilvusVectorStore
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

    def test_upsert_idempotency_is_scoped_to_tenant(self) -> None:
        self.store.upsert("a-1", "t-A", _unit(3, 0), "c-1", "tenant A version")
        self.store.upsert("a-1", "t-B", _unit(3, 0), "c-1", "tenant B version")
        results_a = self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-A")
        results_b = self.store.search_similar(_unit(3, 0), k=5, tenant_id="t-B")
        assert len(results_a) == 1
        assert results_a[0].content == "tenant A version"
        assert len(results_b) == 1
        assert results_b[0].content == "tenant B version"


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


# ===========================================================================
# MilvusVectorStore — Sprint 9 Task 2
# All tests use Milvus Lite (.db file via tmp_path) — no running server needed.
# dim=4 keeps vectors small; behaviour is identical to full-dimension usage.
# ===========================================================================

_DIM = 4


@pytest.fixture()
def store(tmp_path: pytest.TempPathFactory) -> MilvusVectorStore:
    """Fresh Milvus Lite store per test — fully isolated, no server required."""
    s = MilvusVectorStore(uri=str(tmp_path / "test.db"), dim=_DIM)
    yield s
    s.drop()


# ---------------------------------------------------------------------------
# TestMilvusUpsert
# ---------------------------------------------------------------------------

class TestMilvusUpsert:
    def test_upsert_stores_chunk_and_search_finds_it(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-1", "VAT is 9%")
        results = store.search_similar(_unit(_DIM, 0), k=5, tenant_id="t-1")
        assert len(results) == 1
        assert results[0].chunk_id == "c-1"

    def test_upsert_stores_erp_module(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-1", "text", erp_module="finance")
        results = store.search_similar(_unit(_DIM, 0), k=1, tenant_id="t-1")
        assert results[0].erp_module == "finance"

    def test_upsert_erp_module_none_returned_as_none(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-1", "text", erp_module=None)
        results = store.search_similar(_unit(_DIM, 0), k=1, tenant_id="t-1")
        assert results[0].erp_module is None

    def test_upsert_is_idempotent_overwrites_content(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-1", "first version")
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-1", "second version")
        results = store.search_similar(_unit(_DIM, 0), k=10, tenant_id="t-1")
        c1_hits = [r for r in results if r.chunk_id == "c-1"]
        assert len(c1_hits) == 1, "upsert must not create duplicate records"
        assert c1_hits[0].content == "second version"

    def test_upsert_idempotency_is_scoped_to_tenant(self, store: MilvusVectorStore) -> None:
        # Same chunk_id in different tenants must be independent records
        store.upsert("a-1", "t-A", _unit(_DIM, 0), "c-1", "tenant A version")
        store.upsert("a-1", "t-B", _unit(_DIM, 0), "c-1", "tenant B version")
        res_a = store.search_similar(_unit(_DIM, 0), k=5, tenant_id="t-A")
        res_b = store.search_similar(_unit(_DIM, 0), k=5, tenant_id="t-B")
        assert len(res_a) == 1 and res_a[0].content == "tenant A version"
        assert len(res_b) == 1 and res_b[0].content == "tenant B version"

    def test_source_is_asset_id(self, store: MilvusVectorStore) -> None:
        store.upsert("asset-42", "t-1", _unit(_DIM, 0), "c-1", "text")
        results = store.search_similar(_unit(_DIM, 0), k=1, tenant_id="t-1")
        assert results[0].source == "asset-42"


# ---------------------------------------------------------------------------
# TestMilvusSearchSimilar
# ---------------------------------------------------------------------------

class TestMilvusSearchSimilar:
    def test_returns_scored_chunk_instances(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-1", "content A")
        results = store.search_similar(_unit(_DIM, 0), k=5, tenant_id="t-1")
        assert isinstance(results[0], ScoredChunk)

    def test_perfect_cosine_score_is_one(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-1", "text")
        results = store.search_similar(_unit(_DIM, 0), k=1, tenant_id="t-1")
        assert math.isclose(results[0].score, 1.0, abs_tol=1e-5)

    def test_results_ordered_descending_by_score(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-best", "most similar")
        store.upsert("a-1", "t-1", _unit(_DIM, 1), "c-worst", "orthogonal")
        results = store.search_similar(_unit(_DIM, 0), k=5, tenant_id="t-1")
        assert results[0].chunk_id == "c-best"
        assert results[0].score >= results[1].score

    def test_k_limits_number_of_results(self, store: MilvusVectorStore) -> None:
        for i in range(5):
            store.upsert("a-1", "t-1", _unit(_DIM, i % _DIM), f"c-{i}", f"chunk {i}")
        results = store.search_similar(_unit(_DIM, 0), k=2, tenant_id="t-1")
        assert len(results) == 2

    def test_empty_store_returns_empty_list(self, store: MilvusVectorStore) -> None:
        results = store.search_similar(_unit(_DIM, 0), k=5, tenant_id="t-1")
        assert results == []

    def test_no_chunks_for_tenant_returns_empty_list(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-other", _unit(_DIM, 0), "c-1", "text")
        results = store.search_similar(_unit(_DIM, 0), k=5, tenant_id="t-nobody")
        assert results == []


# ---------------------------------------------------------------------------
# TestMilvusTenantIsolation
# ---------------------------------------------------------------------------

class TestMilvusTenantIsolation:
    def test_tenant_a_chunks_invisible_to_tenant_b(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-A", _unit(_DIM, 0), "c-A", "tenant A chunk")
        store.upsert("a-1", "t-B", _unit(_DIM, 0), "c-B", "tenant B chunk")
        results = store.search_similar(_unit(_DIM, 0), k=10, tenant_id="t-A")
        ids = {r.chunk_id for r in results}
        assert "c-A" in ids
        assert "c-B" not in ids

    def test_erp_module_filter_excludes_other_modules(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-fin", "finance chunk", erp_module="finance")
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-hr", "HR chunk", erp_module="hr")
        results = store.search_similar(_unit(_DIM, 0), k=10, tenant_id="t-1", erp_module="finance")
        ids = {r.chunk_id for r in results}
        assert "c-fin" in ids
        assert "c-hr" not in ids

    def test_no_erp_module_filter_returns_all_modules(self, store: MilvusVectorStore) -> None:
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-fin", "finance", erp_module="finance")
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-hr", "HR", erp_module="hr")
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-none", "no module", erp_module=None)
        results = store.search_similar(_unit(_DIM, 0), k=10, tenant_id="t-1")
        assert len(results) == 3


# ---------------------------------------------------------------------------
# TestMilvusIdempotencyTracking
# ---------------------------------------------------------------------------

class TestMilvusIdempotencyTracking:
    def test_has_vectors_false_before_save_vectors(self, store: MilvusVectorStore) -> None:
        assert store.has_vectors("a-1", "t-1") is False

    def test_has_vectors_true_after_save_vectors(self, store: MilvusVectorStore) -> None:
        store.save_vectors("a-1", "t-1", 5)
        assert store.has_vectors("a-1", "t-1") is True

    def test_count_zero_before_save_vectors(self, store: MilvusVectorStore) -> None:
        assert store.count("a-1", "t-1") == 0

    def test_count_returns_saved_value(self, store: MilvusVectorStore) -> None:
        store.save_vectors("a-1", "t-1", 12)
        assert store.count("a-1", "t-1") == 12

    def test_save_vectors_overwrites_previous_count(self, store: MilvusVectorStore) -> None:
        store.save_vectors("a-1", "t-1", 5)
        store.save_vectors("a-1", "t-1", 10)
        assert store.count("a-1", "t-1") == 10

    def test_has_vectors_scoped_to_tenant(self, store: MilvusVectorStore) -> None:
        store.save_vectors("a-1", "t-1", 3)
        assert store.has_vectors("a-1", "t-1") is True
        assert store.has_vectors("a-1", "t-other") is False


# ---------------------------------------------------------------------------
# TestMilvusContentTruncation
# ---------------------------------------------------------------------------

class TestMilvusContentTruncation:
    def test_content_exceeding_max_length_is_truncated_and_stored(
        self, store: MilvusVectorStore
    ) -> None:
        from src.infrastructure.vector_store.milvus_vector_store import _CONTENT_MAX_LEN

        oversized = "x" * (_CONTENT_MAX_LEN + 500)
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-big", oversized)
        results = store.search_similar(_unit(_DIM, 0), k=1, tenant_id="t-1")
        assert len(results) == 1
        assert len(results[0].content) == _CONTENT_MAX_LEN

    def test_content_within_max_length_stored_exactly(self, store: MilvusVectorStore) -> None:
        from src.infrastructure.vector_store.milvus_vector_store import _CONTENT_MAX_LEN

        exact = "y" * (_CONTENT_MAX_LEN - 1)
        store.upsert("a-1", "t-1", _unit(_DIM, 0), "c-ok", exact)
        results = store.search_similar(_unit(_DIM, 0), k=1, tenant_id="t-1")
        assert results[0].content == exact


# ---------------------------------------------------------------------------
# TestMilvusPortCompliance
# ---------------------------------------------------------------------------

class TestMilvusPortCompliance:
    def test_milvus_vector_store_is_vector_store_port(self, store: MilvusVectorStore) -> None:
        assert isinstance(store, VectorStorePort)

    def test_drop_clears_metadata_and_allows_fresh_start(self, tmp_path: pytest.TempPathFactory) -> None:
        db = str(tmp_path / "drop_test.db")
        s = MilvusVectorStore(uri=db, dim=_DIM)
        s.save_vectors("a-1", "t-1", 7)
        s.upsert("a-1", "t-1", _unit(_DIM, 0), "c-1", "text")
        s.drop()
        # Re-create — collection and metadata must be gone
        s2 = MilvusVectorStore(uri=db, dim=_DIM)
        assert s2.has_vectors("a-1", "t-1") is False
        assert s2.search_similar(_unit(_DIM, 0), k=5, tenant_id="t-1") == []
        s2.drop()
