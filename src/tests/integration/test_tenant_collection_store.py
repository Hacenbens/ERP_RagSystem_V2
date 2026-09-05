"""
Per-tenant collections, and who owns the connection — Sprint 12 (S12·4).

Two things are asserted here.

**Isolation is structural.** Every tenant gets its own collection, so
cross-tenant results are not filtered out — they are never fetched. The
previous layout kept one shared collection and filtered on a tenant_id field,
which is only as good as every query remembering the filter. The SQL half of
this system shipped exactly that bug: a literal tenant that bypassed the
filter and read across tenants.

**The connection has one owner.** The DI factory builds the provider, connects
it, and hands it over. The store never opens or closes anything. A store that
could reconnect would let a connection be opened from wherever a query ran —
in a Celery fork, mid-request, inside a retry — with nothing owning when it
closes.
"""
from __future__ import annotations

import inspect
import os
from collections.abc import Iterator

import pytest

from src.domain.ports.vector_store_port import VectorStorePort
from src.infrastructure.vector_store.milvus_provider import MilvusVectorDBProvider
from src.infrastructure.vector_store.tenant_collection_vector_store import (
    TenantCollectionVectorStore,
)

URI = os.environ.get("MILVUS_TEST_SERVER_URI", "")
DIM = 4
FERZA, ACME = "tenant-ferza", "acme"


def _unit(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i % DIM] = 1.0
    return v


# ---------------------------------------------------------------------------
# Connection ownership — no database needed
# ---------------------------------------------------------------------------

class TestOnlyTheProviderOwnsTheConnection:
    def test_the_store_has_no_connect_or_disconnect(self):
        """It cannot open a connection because it has no way to."""
        assert not hasattr(TenantCollectionVectorStore, "connect")
        assert not hasattr(TenantCollectionVectorStore, "disconnect")

    def test_the_store_never_calls_them_on_the_provider(self):
        """Having a connected provider is not licence to manage it."""
        source = inspect.getsource(TenantCollectionVectorStore)

        assert ".connect(" not in source
        assert ".disconnect(" not in source

    def test_the_store_does_not_construct_a_provider(self):
        """It receives one. Constructing its own would be a second owner."""
        source = inspect.getsource(TenantCollectionVectorStore)

        assert "MilvusVectorDBProvider(" not in source

    def test_the_factory_connects_before_building_the_store(self, monkeypatch, tmp_path):
        """The single place a connection is opened."""
        from src.infrastructure.di import factory

        calls: list[str] = []

        class _RecordingProvider(MilvusVectorDBProvider):
            def __init__(self, *args, **kwargs) -> None:
                calls.append("construct")
                assert kwargs.get("auto_connect") is False, (
                    "construction must not connect as a side effect"
                )
                super().__init__(*args, **kwargs)

            def connect(self) -> None:
                calls.append("connect")

        monkeypatch.setattr(factory, "MilvusVectorDBProvider", _RecordingProvider)
        monkeypatch.setattr(
            factory, "TenantCollectionVectorStore",
            lambda provider, embedding_size: calls.append("build_store"),
        )
        monkeypatch.setenv("MILVUS_DB_URI", str(tmp_path / "x.db"))

        factory._select_vector_store(dim=DIM)

        assert calls == ["construct", "connect", "build_store"]

    def test_no_uri_means_no_connection_at_all(self, monkeypatch):
        from src.infrastructure.di import factory
        from src.infrastructure.vector_store.in_memory_vector_store import (
            InMemoryVectorStore,
        )

        monkeypatch.delenv("MILVUS_DB_URI", raising=False)

        assert isinstance(factory._select_vector_store(dim=DIM), InMemoryVectorStore)


# ---------------------------------------------------------------------------
# Behaviour — against a real server
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not URI, reason="MILVUS_TEST_SERVER_URI not set")
class TestPerTenantCollections:
    @pytest.fixture()
    def store(self) -> Iterator[TenantCollectionVectorStore]:
        provider = MilvusVectorDBProvider(
            URI, default_embedding_size=DIM, auto_connect=False
        )
        provider.connect()
        s = TenantCollectionVectorStore(provider=provider, embedding_size=DIM)
        for tenant in (FERZA, ACME):
            s.drop_tenant(tenant)
        yield s
        for tenant in (FERZA, ACME):
            s.drop_tenant(tenant)
        provider.disconnect()

    def test_it_implements_the_port(self, store):
        assert isinstance(store, VectorStorePort)

    def test_each_tenant_gets_its_own_collection(self, store):
        assert store._chunks(FERZA) != store._chunks(ACME)

    def test_a_chunk_is_retrievable_by_its_tenant(self, store):
        store.upsert("A1", FERZA, _unit(0), "c1", "requisitions need approval")

        hits = store.search_similar(_unit(0), 5, FERZA)

        assert [h.content for h in hits] == ["requisitions need approval"]
        assert hits[0].source == "A1"

    def test_another_tenant_retrieves_nothing(self, store):
        """Not filtered out — never fetched. The collection is the boundary."""
        store.upsert("A1", FERZA, _unit(0), "c1", "ferza policy")

        assert store.search_similar(_unit(0), 5, ACME) == []

    def test_two_tenants_holding_the_same_vector_stay_separate(self, store):
        store.upsert("A1", FERZA, _unit(0), "c1", "ferza copy")
        store.upsert("A1", ACME, _unit(0), "c1", "acme copy")

        assert [h.content for h in store.search_similar(_unit(0), 5, FERZA)] == ["ferza copy"]
        assert [h.content for h in store.search_similar(_unit(0), 5, ACME)] == ["acme copy"]

    def test_re_upserting_a_chunk_does_not_duplicate_it(self, store):
        store.upsert("A1", FERZA, _unit(0), "c1", "first")
        store.upsert("A1", FERZA, _unit(0), "c1", "second")

        hits = store.search_similar(_unit(0), 5, FERZA)

        assert len(hits) == 1
        assert hits[0].content == "second"

    def test_limit_is_respected(self, store):
        for i in range(5):
            store.upsert("A1", FERZA, _unit(i), f"c{i}", f"chunk {i}")

        assert len(store.search_similar(_unit(0), 2, FERZA)) == 2

    def test_erp_module_narrows_within_the_tenant(self, store):
        store.upsert("A1", FERZA, _unit(0), "c1", "finance doc", erp_module="finance")
        store.upsert("A1", FERZA, _unit(0), "c2", "hr doc", erp_module="hr")

        hits = store.search_similar(_unit(0), 5, FERZA, erp_module="finance")

        assert [h.content for h in hits] == ["finance doc"]

    def test_a_chunk_is_findable_immediately_after_writing(self, store):
        """Upload then ask about it, with no sleep in between."""
        store.upsert("A1", FERZA, _unit(0), "c1", "just written")

        assert store.search_similar(_unit(0), 5, FERZA)


@pytest.mark.skipif(not URI, reason="MILVUS_TEST_SERVER_URI not set")
class TestEmbedState:
    @pytest.fixture()
    def store(self) -> Iterator[TenantCollectionVectorStore]:
        provider = MilvusVectorDBProvider(
            URI, default_embedding_size=DIM, auto_connect=False
        )
        provider.connect()
        s = TenantCollectionVectorStore(provider=provider, embedding_size=DIM)
        s.drop_tenant(FERZA)
        yield s
        s.drop_tenant(FERZA)
        provider.disconnect()

    def test_an_unembedded_asset_reads_as_absent(self, store):
        assert store.has_vectors("never-seen", FERZA) is False
        assert store.count("never-seen", FERZA) == 0

    def test_a_finished_asset_is_marked(self, store):
        store.upsert("A1", FERZA, _unit(0), "c1", "text")
        store.save_vectors("A1", FERZA, 1)

        assert store.has_vectors("A1", FERZA) is True
        assert store.count("A1", FERZA) == 1

    def test_a_half_finished_embed_does_not_read_as_done(self, store):
        """save_vectors runs last. Chunks alone must not mean finished, or a
        run that died half way is skipped forever."""
        store.upsert("A1", FERZA, _unit(0), "c1", "first chunk")

        assert store.has_vectors("A1", FERZA) is False

    def test_the_marker_never_appears_in_search_results(self, store):
        """It lives in a sibling collection, not among the chunks."""
        store.upsert("A1", FERZA, _unit(0), "c1", "real chunk")
        store.save_vectors("A1", FERZA, 1)

        assert [h.content for h in store.search_similar(_unit(0), 10, FERZA)] == ["real chunk"]

    def test_state_is_scoped_to_the_tenant(self, store):
        store.save_vectors("A1", FERZA, 3)

        assert store.has_vectors("A1", ACME) is False

    def test_a_second_store_sees_the_marker(self, store):
        """Two processes share it; the worker and the API must agree."""
        store.save_vectors("A1", FERZA, 7)

        other = TenantCollectionVectorStore(
            provider=MilvusVectorDBProvider(URI, default_embedding_size=DIM),
            embedding_size=DIM,
        )
        assert other.count("A1", FERZA) == 7

    def test_dropping_a_tenant_removes_chunks_and_state(self, store):
        store.upsert("A1", FERZA, _unit(0), "c1", "text")
        store.save_vectors("A1", FERZA, 1)

        store.drop_tenant(FERZA)

        assert store.search_similar(_unit(0), 5, FERZA) == []
        assert store.has_vectors("A1", FERZA) is False
