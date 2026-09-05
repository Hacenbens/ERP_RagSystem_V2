"""
Reconciling chunks against vectors — Sprint 12 (S12·7).

The failure this repairs is silent by construction. Chunks are written by the
ingest task, vectors by the embed task; an asset that stops in between is
stored, listed, and returns nothing when asked about. Nothing errors. The user
sees "not grounded", which is indistinguishable from the document not
containing the answer.

Tests run the real use case over real in-memory stores, not mocks, because the
thing being verified is agreement between two stores.
"""
from __future__ import annotations

import pytest

from src.domain.chunk import Chunk
from src.domain.models.embedding_consistency import AssetEmbedState
from src.domain.ports.embedding_port import EmbeddingPort
from src.infrastructure.persistence.chunk_store import InMemoryChunkStore
from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore
from src.use_cases.reembed_assets import ReembedAssetsUseCase
from src.use_cases.tasks.embed_asset_use_case import EmbedAssetUseCase

FERZA, ACME = "ferza", "acme"


class _Embedder(EmbeddingPort):
    """Deterministic, so a re-embed produces the vector it produced before."""

    def embed(self, text: str) -> list[float]:
        seed = sum(ord(c) for c in text) or 1
        return [1.0, seed % 7 / 7.0, 0.0, 0.0]


class _BrokenEmbedder(EmbeddingPort):
    def embed(self, text: str) -> list[float]:
        raise ConnectionError("embedding service unreachable")


@pytest.fixture()
def stores():
    return InMemoryChunkStore(), InMemoryVectorStore()


def _use_case(chunks, vectors, embedder=None) -> ReembedAssetsUseCase:
    return ReembedAssetsUseCase(
        chunk_store=chunks,
        vector_store=vectors,
        embed_uc=EmbedAssetUseCase(
            vector_store=vectors,
            chunk_store=chunks,
            embedding_port=embedder or _Embedder(),
        ),
    )


def _ingest(chunks, asset: str, tenant: str, n: int, strategy: str = "SOP") -> None:
    """Ingest without embedding — the exact state this tool exists to find."""
    chunks.save_chunks(asset, tenant, [
        Chunk(text=f"{asset} chunk {i}", chunk_id=f"{asset}-c{i}",
              metadata={"chunk_strategy": strategy})
        for i in range(n)
    ])


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

class TestInspectClassifiesEachAsset:
    def test_ingested_but_never_embedded_is_missing(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 3)

        found = _use_case(chunks, vectors).inspect()

        assert [a.state for a in found] == [AssetEmbedState.MISSING]
        assert found[0].chunk_count == 3
        assert found[0].vector_count == 0

    def test_fully_embedded_is_consistent(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 3)
        _use_case(chunks, vectors).execute()

        found = _use_case(chunks, vectors).inspect()

        assert [a.state for a in found] == [AssetEmbedState.CONSISTENT]

    def test_a_partial_embed_is_mismatched(self, stores):
        """The worker died after 1 of 3 chunks and wrote a marker anyway."""
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 3)
        vectors.save_vectors("A1", FERZA, 1)

        found = _use_case(chunks, vectors).inspect()

        assert found[0].state == AssetEmbedState.MISMATCHED
        assert (found[0].chunk_count, found[0].vector_count) == (3, 1)

    def test_an_asset_whose_chunks_are_gone_is_invisible_to_the_scan(self, stores):
        """The documented blind spot, pinned so it cannot change silently.

        The scan enumerates from the chunk store, so a completion marker whose
        chunks were deleted is never examined. Re-embedding could not repair it
        anyway — there is nothing to embed — but it does mean this tool is not
        a full integrity check. Detecting it needs enumeration on
        VectorStorePort, which is deliberately not there.
        """
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 1)
        chunks.save_chunks("A2", FERZA, [Chunk(text="t", chunk_id="c")])
        vectors.save_vectors("A2", FERZA, 5)
        chunks.delete_by_asset("A2", FERZA)

        scanned = {a.ref.asset_id for a in _use_case(chunks, vectors).inspect()}

        assert scanned == {"A1"}
        assert vectors.has_vectors("A2", FERZA), "the stale marker is still there"

    def test_inspect_changes_nothing(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 2)

        _use_case(chunks, vectors).inspect()

        assert vectors.count("A1", FERZA) == 0


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------

class TestExecuteRepairs:
    def test_a_missing_asset_becomes_searchable(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 2)

        report = _use_case(chunks, vectors).execute()

        assert report.vectors_written == 2
        assert vectors.has_vectors("A1", FERZA)
        hits = vectors.search_similar(_Embedder().embed("A1 chunk 0"), 5, FERZA)
        assert [h.content for h in hits][:1] == ["A1 chunk 0"]

    def test_a_partial_embed_is_completed(self, stores):
        """The blocker: EmbedAssetUseCase refuses an asset already marked done."""
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 3)
        vectors.save_vectors("A1", FERZA, 1)

        report = _use_case(chunks, vectors).execute()

        assert report.vectors_written == 3
        assert vectors.count("A1", FERZA) == 3

    def test_a_consistent_asset_is_left_alone(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 2)
        _use_case(chunks, vectors).execute()

        second = _use_case(chunks, vectors).execute()

        assert second.repaired == []
        assert second.is_consistent

    def test_running_twice_does_not_duplicate_vectors(self, stores):
        """Upserts are keyed by chunk_id, so a forced re-embed converges."""
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 2)

        _use_case(chunks, vectors).execute()
        _use_case(chunks, vectors).execute()

        assert len(vectors.search_similar(_Embedder().embed("A1 chunk 0"), 50, FERZA)) == 2

    def test_it_reports_consistent_when_everything_is_repaired(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 2)
        _ingest(chunks, "A2", ACME, 1)

        assert _use_case(chunks, vectors).execute().is_consistent


class TestTenantScoping:
    def test_one_tenant_can_be_repaired_alone(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 2)
        _ingest(chunks, "A2", ACME, 2)

        _use_case(chunks, vectors).execute(tenant_id=FERZA)

        assert vectors.has_vectors("A1", FERZA)
        assert not vectors.has_vectors("A2", ACME)

    def test_scanning_all_tenants_is_the_default(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 1)
        _ingest(chunks, "A2", ACME, 1)

        report = _use_case(chunks, vectors).execute()

        assert {a.ref.tenant_id for a in report.scanned} == {FERZA, ACME}

    def test_repaired_vectors_stay_inside_their_tenant(self, stores):
        """Ferza may match its own chunks; it must never see acme's."""
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 1)
        _ingest(chunks, "A2", ACME, 1)

        _use_case(chunks, vectors).execute()

        for tenant, own, foreign in ((FERZA, "A1", "A2"), (ACME, "A2", "A1")):
            hits = vectors.search_similar(_Embedder().embed("A2 chunk 0"), 50, tenant)
            sources = {h.source for h in hits}
            assert sources == {own}, f"{tenant} saw {sources}, expected only {own}"
            assert foreign not in sources


class TestDryRun:
    def test_it_writes_nothing(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 3)

        _use_case(chunks, vectors).execute(dry_run=True)

        assert vectors.count("A1", FERZA) == 0

    def test_it_still_reports_what_would_change(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 3)

        report = _use_case(chunks, vectors).execute(dry_run=True)

        assert [a.state for a in report.scanned] == [AssetEmbedState.MISSING]
        assert report.repaired == []


class TestFailureHandling:
    def test_one_failing_asset_does_not_abandon_the_rest(self, stores):
        """A reconciliation is most useful when it fixes all it can."""
        chunks, vectors = stores
        _ingest(chunks, "good", FERZA, 1)
        _ingest(chunks, "bad", FERZA, 1)

        class _FailsOnce(EmbeddingPort):
            def embed(self, text: str) -> list[float]:
                if text.startswith("bad"):
                    raise ConnectionError("embedding service unreachable")
                return _Embedder().embed(text)

        report = _use_case(chunks, vectors, _FailsOnce()).execute()

        assert vectors.has_vectors("good", FERZA)
        assert [f.ref.asset_id for f in report.failures] == ["bad"]

    def test_a_failed_run_is_not_reported_consistent(self, stores):
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 1)

        report = _use_case(chunks, vectors, _BrokenEmbedder()).execute()

        assert not report.is_consistent
        assert report.failures[0].error

    def test_a_failed_asset_is_not_marked_embedded(self, stores):
        """Otherwise the next run would skip it and the gap becomes permanent."""
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 1)

        _use_case(chunks, vectors, _BrokenEmbedder()).execute()

        assert not vectors.has_vectors("A1", FERZA)


class TestProvenance:
    def test_the_chunk_strategy_is_read_back_from_the_chunks(self, stores):
        """A reconciliation should not force one strategy onto every asset."""
        chunks, vectors = stores
        _ingest(chunks, "A1", FERZA, 1, strategy="BPMN")
        uc = _use_case(chunks, vectors)

        asset = uc.inspect()[0]

        assert uc._strategy_for(asset) == "BPMN"

    def test_chunks_without_a_recorded_strategy_report_unknown(self, stores):
        chunks, vectors = stores
        chunks.save_chunks("A1", FERZA, [Chunk(text="t", chunk_id="c")])
        uc = _use_case(chunks, vectors)

        assert uc._strategy_for(uc.inspect()[0]) == "UNKNOWN"


class TestListAssets:
    def test_it_spans_every_tenant(self, stores):
        chunks, _ = stores
        _ingest(chunks, "A1", FERZA, 1)
        _ingest(chunks, "A2", ACME, 1)

        assert {r.tenant_id for r in chunks.list_assets()} == {FERZA, ACME}

    def test_an_asset_whose_chunks_were_deleted_is_not_listed(self, stores):
        chunks, _ = stores
        _ingest(chunks, "A1", FERZA, 1)
        chunks.delete_by_asset("A1", FERZA)

        assert chunks.list_assets() == []
