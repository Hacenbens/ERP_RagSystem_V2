"""
Integration tests — MilvusVectorStore embed pipeline (Sprint 9 Task 4)

Strategy
--------
- MilvusVectorStore backed by a Milvus-Lite .db file (tmp_path fixture per test).
- EmbedAssetUseCase wired with real MilvusVectorStore + stub ChunkStore +
  stub EmbeddingPort.
- Embedding dim=4 for speed; deterministic unit vectors give controllable
  cosine-similarity ordering — no network calls needed.
- No mocks: every assertion exercises the real Milvus Lite write/read path.

Test categories
---------------
1. Full pipeline       — embed chunks, search finds correct results
2. Tenant isolation    — cross-tenant search must return nothing (security gate)
3. ERP module filter   — filter by module returns only matching chunks
4. Upsert idempotency  — same chunk_id does not create duplicates
"""
from __future__ import annotations

import pytest

from src.domain.chunk import Chunk
from src.domain.ports.chunk_store_port import ChunkStorePort
from src.domain.ports.embedding_port import EmbeddingPort
from src.infrastructure.vector_store.milvus_vector_store import MilvusVectorStore
from src.use_cases.tasks.embed_asset_use_case import (
    AssetAlreadyEmbeddedError,
    EmbedAssetUseCase,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIM = 4  # small dimension — Milvus Lite, fast tests
_ASSET_A = "asset-alpha-001"
_ASSET_B = "asset-beta-002"
_TENANT_A = "tenant-acme"
_TENANT_B = "tenant-ferza"

# Orthogonal unit vectors (cosine = 1.0 between identical, 0.0 between orthogonal)
_VEC_X = [1.0, 0.0, 0.0, 0.0]
_VEC_Y = [0.0, 1.0, 0.0, 0.0]
_VEC_Z = [0.0, 0.0, 1.0, 0.0]
_VEC_W = [0.0, 0.0, 0.0, 1.0]


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _FixedEmbeddingPort(EmbeddingPort):
    """Returns a pre-configured vector for a given text key; raises for unknowns."""

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping

    def embed(self, text: str) -> list[float]:
        if text not in self._mapping:
            raise ValueError(f"No embedding configured for text: {text!r}")
        return list(self._mapping[text])


class _MemoryChunkStore(ChunkStorePort):
    """In-memory chunk store keyed by (asset_id, tenant_id)."""

    def __init__(self, chunks_by_key: dict[tuple[str, str], list[Chunk]] | None = None) -> None:
        self._store: dict[tuple[str, str], list[Chunk]] = chunks_by_key or {}

    def save_chunks(self, asset_id: str, tenant_id: str, chunks: list[Chunk]) -> int:
        self._store[(asset_id, tenant_id)] = list(chunks)
        return len(chunks)

    def find_by_asset(self, asset_id: str, tenant_id: str) -> list[Chunk]:
        return list(self._store.get((asset_id, tenant_id), []))

    def delete_by_asset(self, asset_id: str, tenant_id: str) -> int:
        removed = self._store.pop((asset_id, tenant_id), [])
        return len(removed)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def milvus_store(tmp_path):
    """Fresh MilvusVectorStore backed by a temp .db file — isolated per test."""
    store = MilvusVectorStore(uri=str(tmp_path / "test.db"), dim=_DIM)
    yield store
    store.drop()


def _make_use_case(
    store: MilvusVectorStore,
    chunks: list[Chunk],
    asset_id: str = _ASSET_A,
    tenant_id: str = _TENANT_A,
    embedding_map: dict[str, list[float]] | None = None,
) -> EmbedAssetUseCase:
    """Wire EmbedAssetUseCase with the given store, chunks and embedding map."""
    chunk_store = _MemoryChunkStore({(asset_id, tenant_id): chunks})
    emb_map = embedding_map or {c.text: _VEC_X for c in chunks}
    return EmbedAssetUseCase(
        vector_store=store,
        chunk_store=chunk_store,
        embedding_port=_FixedEmbeddingPort(emb_map),
    )


# ===========================================================================
# 1. Full pipeline — embed → search
# ===========================================================================

class TestMilvusFullPipeline:
    def test_embed_then_search_finds_the_stored_chunk(self, milvus_store):
        chunk = Chunk(text="invoice processing SOP", chunk_id="chunk-001")
        uc = _make_use_case(
            milvus_store, [chunk],
            embedding_map={"invoice processing SOP": _VEC_X},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="t1")

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=5, tenant_id=_TENANT_A
        )

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-001"
        assert results[0].content == "invoice processing SOP"

    def test_embed_result_vector_count_matches_chunk_count(self, milvus_store):
        chunks = [
            Chunk(text="chunk A", chunk_id="cA"),
            Chunk(text="chunk B", chunk_id="cB"),
            Chunk(text="chunk C", chunk_id="cC"),
        ]
        uc = _make_use_case(
            milvus_store, chunks,
            embedding_map={"chunk A": _VEC_X, "chunk B": _VEC_Y, "chunk C": _VEC_Z},
        )
        result = uc.execute(
            asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="t2"
        )

        assert result.vector_count == 3

    def test_embed_multiple_chunks_search_returns_closest_first(self, milvus_store):
        """Query vector _VEC_Y → chunk-B must rank before chunk-A (orthogonal)."""
        chunks = [
            Chunk(text="finance report", chunk_id="chunk-A"),
            Chunk(text="hr policy doc", chunk_id="chunk-B"),
        ]
        uc = _make_use_case(
            milvus_store, chunks,
            embedding_map={"finance report": _VEC_X, "hr policy doc": _VEC_Y},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="t3")

        results = milvus_store.search_similar(
            query_embedding=_VEC_Y, k=2, tenant_id=_TENANT_A
        )

        assert len(results) == 2
        assert results[0].chunk_id == "chunk-B"
        assert results[1].chunk_id == "chunk-A"

    def test_has_vectors_true_after_embed(self, milvus_store):
        chunk = Chunk(text="sop text", chunk_id="ch-1")
        uc = _make_use_case(milvus_store, [chunk], embedding_map={"sop text": _VEC_X})
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="t4")

        assert milvus_store.has_vectors(_ASSET_A, _TENANT_A) is True

    def test_count_after_embed_matches_chunk_count(self, milvus_store):
        chunks = [Chunk(text=f"text-{i}", chunk_id=f"ch-{i}") for i in range(3)]
        uc = _make_use_case(
            milvus_store, chunks,
            embedding_map={f"text-{i}": _VEC_X for i in range(3)},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="t5")

        assert milvus_store.count(_ASSET_A, _TENANT_A) == 3

    def test_search_returns_correct_source_asset_id(self, milvus_store):
        chunk = Chunk(text="procurement workflow", chunk_id="ch-src")
        uc = _make_use_case(
            milvus_store, [chunk],
            embedding_map={"procurement workflow": _VEC_X},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="t6")

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=1, tenant_id=_TENANT_A
        )

        assert results[0].source == _ASSET_A

    def test_search_k_limits_result_count(self, milvus_store):
        chunks = [Chunk(text=f"doc-{i}", chunk_id=f"c-{i}") for i in range(5)]
        uc = _make_use_case(
            milvus_store, chunks,
            embedding_map={f"doc-{i}": _VEC_X for i in range(5)},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="t7")

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=2, tenant_id=_TENANT_A
        )

        assert len(results) <= 2

    def test_search_empty_store_returns_empty_list(self, milvus_store):
        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=5, tenant_id=_TENANT_A
        )
        assert results == []


# ===========================================================================
# 2. Tenant isolation — security gate
# ===========================================================================

class TestMilvusTenantIsolation:
    def test_search_cross_tenant_returns_empty(self, milvus_store):
        """Embeddings stored under tenant-A must not surface for tenant-B queries."""
        chunk = Chunk(text="sensitive HR data", chunk_id="sensitive-ch")
        uc = _make_use_case(
            milvus_store, [chunk],
            asset_id=_ASSET_A, tenant_id=_TENANT_A,
            embedding_map={"sensitive HR data": _VEC_X},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="ti-1")

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=5, tenant_id=_TENANT_B
        )

        assert results == []

    def test_same_asset_both_tenants_each_see_only_their_chunks(self, milvus_store):
        """Two tenants embed the same asset; queries are isolated by tenant."""
        chunk_a = Chunk(text="acme payroll", chunk_id="ch-acme")
        chunk_b = Chunk(text="ferza payroll", chunk_id="ch-ferza")

        chunk_store_a = _MemoryChunkStore({(_ASSET_A, _TENANT_A): [chunk_a]})
        chunk_store_b = _MemoryChunkStore({(_ASSET_A, _TENANT_B): [chunk_b]})
        emb_port = _FixedEmbeddingPort({"acme payroll": _VEC_X, "ferza payroll": _VEC_Y})

        uc_a = EmbedAssetUseCase(vector_store=milvus_store, chunk_store=chunk_store_a, embedding_port=emb_port)
        uc_b = EmbedAssetUseCase(vector_store=milvus_store, chunk_store=chunk_store_b, embedding_port=emb_port)

        uc_a.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="ti-2a")
        uc_b.execute(asset_id=_ASSET_A, tenant_id=_TENANT_B, chunk_strategy="sop", task_id="ti-2b")

        results_a = milvus_store.search_similar(_VEC_X, k=5, tenant_id=_TENANT_A)
        results_b = milvus_store.search_similar(_VEC_Y, k=5, tenant_id=_TENANT_B)

        assert all(r.chunk_id == "ch-acme" for r in results_a)
        assert all(r.chunk_id == "ch-ferza" for r in results_b)

    def test_has_vectors_scoped_to_tenant(self, milvus_store):
        """has_vectors for a different tenant must return False."""
        chunk = Chunk(text="hr sop", chunk_id="ch-hr")
        uc = _make_use_case(
            milvus_store, [chunk],
            asset_id=_ASSET_A, tenant_id=_TENANT_A,
            embedding_map={"hr sop": _VEC_X},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="ti-3")

        assert milvus_store.has_vectors(_ASSET_A, _TENANT_A) is True
        assert milvus_store.has_vectors(_ASSET_A, _TENANT_B) is False

    def test_count_is_zero_for_unembedded_tenant(self, milvus_store):
        chunk = Chunk(text="logistics data", chunk_id="ch-log")
        uc = _make_use_case(
            milvus_store, [chunk],
            asset_id=_ASSET_A, tenant_id=_TENANT_A,
            embedding_map={"logistics data": _VEC_X},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="ti-4")

        assert milvus_store.count(_ASSET_A, _TENANT_B) == 0


# ===========================================================================
# 3. ERP module filter
# ===========================================================================

class TestMilvusErpModuleFilter:
    def _embed_hr_and_finance(self, store: MilvusVectorStore) -> None:
        hr_chunk = Chunk(
            text="hr leave policy",
            chunk_id="hr-ch",
            metadata={"erp_module": "hr"},
        )
        finance_chunk = Chunk(
            text="finance budget plan",
            chunk_id="fin-ch",
            metadata={"erp_module": "finance"},
        )
        chunk_store = _MemoryChunkStore({
            (_ASSET_A, _TENANT_A): [hr_chunk, finance_chunk]
        })
        emb_port = _FixedEmbeddingPort({
            "hr leave policy": _VEC_X,
            "finance budget plan": _VEC_Y,
        })
        uc = EmbedAssetUseCase(
            vector_store=store, chunk_store=chunk_store, embedding_port=emb_port
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="mod-setup")

    def test_module_filter_returns_only_matching_chunks(self, milvus_store):
        self._embed_hr_and_finance(milvus_store)

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=5, tenant_id=_TENANT_A, erp_module="hr"
        )

        assert len(results) == 1
        assert results[0].chunk_id == "hr-ch"
        assert results[0].erp_module == "hr"

    def test_search_without_module_filter_returns_all_chunks(self, milvus_store):
        self._embed_hr_and_finance(milvus_store)

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=5, tenant_id=_TENANT_A
        )

        chunk_ids = {r.chunk_id for r in results}
        assert "hr-ch" in chunk_ids
        assert "fin-ch" in chunk_ids

    def test_module_filter_no_match_returns_empty(self, milvus_store):
        self._embed_hr_and_finance(milvus_store)

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=5, tenant_id=_TENANT_A, erp_module="procurement"
        )

        assert results == []

    def test_erp_module_none_stored_as_none_on_read(self, milvus_store):
        """Chunk with no erp_module metadata must round-trip as None."""
        chunk = Chunk(text="generic doc", chunk_id="gen-ch")
        uc = _make_use_case(
            milvus_store, [chunk],
            embedding_map={"generic doc": _VEC_X},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="mod-none")

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=1, tenant_id=_TENANT_A
        )

        assert results[0].erp_module is None


# ===========================================================================
# 4. Upsert idempotency — same chunk_id must not produce duplicates
# ===========================================================================

class TestMilvusUpsertIdempotency:
    def test_upsert_same_chunk_twice_no_duplicate_in_search(self, milvus_store):
        """Re-upserting the same chunk_id must overwrite, not append."""
        milvus_store.upsert(
            asset_id=_ASSET_A, tenant_id=_TENANT_A,
            embedding=_VEC_X, chunk_id="dup-ch", content="first version",
        )
        milvus_store.upsert(
            asset_id=_ASSET_A, tenant_id=_TENANT_A,
            embedding=_VEC_X, chunk_id="dup-ch", content="second version",
        )

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=10, tenant_id=_TENANT_A
        )

        dup_hits = [r for r in results if r.chunk_id == "dup-ch"]
        assert len(dup_hits) == 1

    def test_upsert_same_chunk_updates_content(self, milvus_store):
        """The second upsert's content must win."""
        milvus_store.upsert(
            asset_id=_ASSET_A, tenant_id=_TENANT_A,
            embedding=_VEC_X, chunk_id="upd-ch", content="old content",
        )
        milvus_store.upsert(
            asset_id=_ASSET_A, tenant_id=_TENANT_A,
            embedding=_VEC_X, chunk_id="upd-ch", content="updated content",
        )

        results = milvus_store.search_similar(
            query_embedding=_VEC_X, k=1, tenant_id=_TENANT_A
        )

        assert results[0].content == "updated content"

    def test_embed_use_case_raises_on_second_call_same_asset(self, milvus_store):
        """EmbedAssetUseCase must raise AssetAlreadyEmbeddedError on duplicate embed."""
        chunk = Chunk(text="idempotent doc", chunk_id="idem-ch")
        uc = _make_use_case(
            milvus_store, [chunk],
            embedding_map={"idempotent doc": _VEC_X},
        )
        uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="idem-1")

        with pytest.raises(AssetAlreadyEmbeddedError):
            uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="idem-2")

    def test_embed_use_case_different_asset_not_blocked(self, milvus_store):
        """Second asset for the same tenant must not be blocked by idempotency guard."""
        chunk_a = Chunk(text="asset a doc", chunk_id="a-ch")
        chunk_b = Chunk(text="asset b doc", chunk_id="b-ch")

        chunk_store = _MemoryChunkStore({
            (_ASSET_A, _TENANT_A): [chunk_a],
            (_ASSET_B, _TENANT_A): [chunk_b],
        })
        emb_port = _FixedEmbeddingPort({"asset a doc": _VEC_X, "asset b doc": _VEC_Y})
        uc = EmbedAssetUseCase(
            vector_store=milvus_store, chunk_store=chunk_store, embedding_port=emb_port
        )

        result_a = uc.execute(asset_id=_ASSET_A, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="idem-a")
        result_b = uc.execute(asset_id=_ASSET_B, tenant_id=_TENANT_A, chunk_strategy="sop", task_id="idem-b")

        assert result_a.vector_count == 1
        assert result_b.vector_count == 1
