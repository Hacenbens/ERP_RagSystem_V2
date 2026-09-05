"""
VectorDBProviderPort against a real Milvus server — Sprint 12 (S12·3).

A driver-level contract: connect, manage collections, insert, search. It sits
below VectorStorePort, which expresses what the use cases need; a provider
implements this, and VectorStorePort is implemented on top of it. Adding
Qdrant or pgvector becomes one new class here.

Run against a server, not mocks. Every defect worth finding in a database
adapter — collection naming rules, read-after-write visibility, duplicate keys
on retry — is a property of the database, and a mock would confirm whichever
behaviour the code already assumed.

    MILVUS_TEST_SERVER_URI=http://127.0.0.1:19530 pytest \\
        src/tests/integration/test_vector_db_provider.py
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from src.domain.models.vector_records import CollectionInfo, VectorSearchHit
from src.domain.ports.vector_db_provider_port import (
    CollectionNotFoundError,
    VectorDBProviderPort,
)
from src.infrastructure.vector_store.milvus_provider import MilvusVectorDBProvider

URI = os.environ.get("MILVUS_TEST_SERVER_URI", "")
DIM = 4

pytestmark = pytest.mark.skipif(
    not URI, reason="MILVUS_TEST_SERVER_URI not set — needs a running Milvus server"
)


def _unit(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i % DIM] = 1.0
    return v


@pytest.fixture()
def provider() -> Iterator[MilvusVectorDBProvider]:
    """A provider that drops whatever collections the test created.

    Teardown diffs the listing rather than intercepting create_collection:
    collections also appear implicitly, on the first insert for a new tenant,
    and a wrapper around one method would miss those.
    """
    p = MilvusVectorDBProvider(URI, default_embedding_size=DIM)
    before = set(p.list_collections())
    yield p
    for name in set(p.list_collections()) - before:
        try:
            p.delete_collection(name)
        except Exception:  # noqa: BLE001 — cleanup must not fail the test
            pass
    p.disconnect()


@pytest.fixture()
def collection(provider: MilvusVectorDBProvider) -> str:
    import uuid

    return f"test_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_it_implements_the_port(self, provider):
        assert isinstance(provider, VectorDBProviderPort)

    def test_connect_is_idempotent(self, provider):
        provider.connect()
        provider.connect()

        assert provider.list_collections() is not None

    def test_disconnect_is_idempotent(self, provider):
        provider.disconnect()
        provider.disconnect()

    def test_it_reconnects_after_disconnect(self, provider):
        provider.disconnect()

        assert provider.list_collections() is not None


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

class TestCollections:
    def test_create_then_exists(self, provider, collection):
        assert provider.is_collection_exists(collection) is False

        provider.create_collection(collection, DIM)

        assert provider.is_collection_exists(collection) is True

    def test_it_appears_in_the_listing(self, provider, collection):
        provider.create_collection(collection, DIM)

        assert collection in provider.list_collections()

    def test_creating_twice_is_a_no_op(self, provider, collection):
        """Two workers racing to create the same collection must both survive."""
        provider.create_collection(collection, DIM)
        provider.insert_one(collection, "keep me", _unit(0))

        provider.create_collection(collection, DIM)

        assert provider.get_collection_info(collection).record_count == 1

    def test_do_recreate_drops_the_records(self, provider, collection):
        provider.create_collection(collection, DIM)
        provider.insert_one(collection, "gone", _unit(0))

        provider.create_collection(collection, DIM, do_recreate=True)

        assert provider.get_collection_info(collection).record_count == 0

    def test_info_reports_count_and_dimension(self, provider, collection):
        provider.create_collection(collection, DIM)
        provider.insert_many(collection, ["a", "b"], [_unit(0), _unit(1)])

        info = provider.get_collection_info(collection)

        assert isinstance(info, CollectionInfo)
        assert info.record_count == 2
        assert info.embedding_size == DIM

    def test_info_on_a_missing_collection_raises(self, provider):
        """Absent differs from empty, and callers need to tell them apart."""
        with pytest.raises(CollectionNotFoundError):
            provider.get_collection_info("definitely_not_here")

    def test_delete_removes_it(self, provider, collection):
        provider.create_collection(collection, DIM)

        provider.delete_collection(collection)

        assert provider.is_collection_exists(collection) is False

    def test_deleting_a_missing_collection_is_a_no_op(self, provider):
        provider.delete_collection("never_existed")


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

class TestInserts:
    def test_insert_one_returns_an_id(self, provider, collection):
        record_id = provider.insert_one(collection, "vat rules", _unit(0))

        assert record_id
        assert provider.get_collection_info(collection).record_count == 1

    def test_insert_one_honours_a_supplied_id(self, provider, collection):
        returned = provider.insert_one(collection, "text", _unit(0), record_id="fixed-1")

        assert returned == "fixed-1"

    def test_reinserting_the_same_id_replaces_rather_than_duplicates(
        self, provider, collection
    ):
        """A retried embed job must converge, not accumulate copies."""
        provider.insert_one(collection, "first", _unit(0), record_id="same")
        provider.insert_one(collection, "second", _unit(0), record_id="same")

        assert provider.get_collection_info(collection).record_count == 1

    def test_insert_many_returns_ids_in_order(self, provider, collection):
        ids = provider.insert_many(
            collection, ["a", "b", "c"], [_unit(0), _unit(1), _unit(2)],
            record_ids=["r1", "r2", "r3"],
        )

        assert ids == ["r1", "r2", "r3"]

    def test_insert_many_respects_the_batch_size(self, provider, collection):
        ids = provider.insert_many(
            collection,
            [f"chunk {i}" for i in range(7)],
            [_unit(i) for i in range(7)],
            batch_size=2,
        )

        assert len(ids) == 7
        assert provider.get_collection_info(collection).record_count == 7

    def test_metadata_survives_the_round_trip(self, provider, collection):
        provider.insert_one(
            collection, "vat rules", _unit(0), {"src": "sop.txt", "page": 3}
        )

        hit = provider.search_by_vector(collection, _unit(0), limit=1)[0]

        assert hit.metadata == {"src": "sop.txt", "page": 3}

    def test_empty_input_inserts_nothing(self, provider, collection):
        assert provider.insert_many(collection, [], []) == []

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"texts": ["a", "b"], "vectors": [[1.0, 0, 0, 0]]},
            {"texts": ["a"], "vectors": [[1.0, 0, 0, 0]], "metadatas": [{}, {}]},
            {"texts": ["a"], "vectors": [[1.0, 0, 0, 0]], "record_ids": ["r1", "r2"]},
        ],
        ids=["vectors", "metadatas", "record_ids"],
    )
    def test_mismatched_list_lengths_raise(self, provider, collection, kwargs):
        """Zipping to the shortest would pair a text with the wrong vector."""
        with pytest.raises(ValueError):
            provider.insert_many(collection, **kwargs)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_it_returns_the_nearest_first(self, provider, collection):
        provider.insert_many(
            collection, ["match", "other"], [_unit(0), _unit(1)],
            record_ids=["r-match", "r-other"],
        )

        hits = provider.search_by_vector(collection, _unit(0), limit=2)

        assert isinstance(hits[0], VectorSearchHit)
        assert hits[0].record_id == "r-match"
        assert hits[0].score >= hits[1].score

    def test_limit_is_respected(self, provider, collection):
        provider.insert_many(
            collection, [f"c{i}" for i in range(5)], [_unit(i) for i in range(5)]
        )

        assert len(provider.search_by_vector(collection, _unit(0), limit=2)) == 2

    def test_a_record_is_findable_immediately_after_writing(self, provider, collection):
        """Upload then ask about it — the interaction this system exists for.

        Milvus serves searches from a bounded-staleness view by default, so
        without Strong consistency a chunk written moments ago is not yet
        findable and the user sees "not grounded", indistinguishable from the
        document not containing the answer.
        """
        provider.insert_one(collection, "just written", _unit(0))

        assert provider.search_by_vector(collection, _unit(0), limit=1)

    def test_searching_a_missing_collection_returns_empty(self, provider):
        """A tenant who has uploaded nothing is a normal state, not an error."""
        assert provider.search_by_vector("no_such_collection", _unit(0)) == []


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

class TestTenantCollections:
    def test_the_name_is_deterministic(self, provider):
        """Any process must resolve a tenant to the same collection."""
        assert provider.tenant_collection("ferza") == provider.tenant_collection("ferza")

    def test_the_name_is_legal_for_milvus(self, provider):
        """Hyphens are rejected, and a leading digit is rejected."""
        name = provider.tenant_collection("tenant-ferza")

        assert "-" not in name
        assert not name[0].isdigit()
        assert len(name) <= 255

    def test_ids_that_sanitise_alike_do_not_collide(self, provider):
        """"acme-eu" and "acme_eu" must not share one collection."""
        assert provider.tenant_collection("acme-eu") != provider.tenant_collection("acme_eu")

    def test_a_very_long_tenant_id_is_still_legal(self, provider):
        name = provider.tenant_collection("t" * 400)

        assert len(name) <= 255

    def test_each_tenant_sees_only_its_own_data(self, provider):
        a, b = "tenant-ferza", "acme"
        provider.create_collection(provider.tenant_collection(a), DIM, do_recreate=True)
        provider.create_collection(provider.tenant_collection(b), DIM, do_recreate=True)
        provider.insert_one(provider.tenant_collection(a), "ferza policy", _unit(0))
        provider.insert_one(provider.tenant_collection(b), "acme policy", _unit(0))

        assert [h.text for h in provider.search_by_tenant(a, _unit(0), 5)] == ["ferza policy"]
        assert [h.text for h in provider.search_by_tenant(b, _unit(0), 5)] == ["acme policy"]

    def test_an_unknown_tenant_returns_nothing(self, provider):
        assert provider.search_by_tenant("never-seen", _unit(0)) == []

    def test_deleting_one_tenant_leaves_the_other_intact(self, provider):
        a, b = "tenant-ferza", "acme"
        provider.create_collection(provider.tenant_collection(a), DIM, do_recreate=True)
        provider.create_collection(provider.tenant_collection(b), DIM, do_recreate=True)
        provider.insert_one(provider.tenant_collection(a), "ferza", _unit(0))
        provider.insert_one(provider.tenant_collection(b), "acme", _unit(0))

        provider.delete_collection(provider.tenant_collection(a))

        assert provider.search_by_tenant(a, _unit(0), 5) == []
        assert len(provider.search_by_tenant(b, _unit(0), 5)) == 1
