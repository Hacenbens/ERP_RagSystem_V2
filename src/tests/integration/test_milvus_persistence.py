"""
Durable Milvus idempotency and the env-var collision — Sprint 11 (G1·2, G1·3).

Two defects kept Milvus from ever being usable:

  G1·2  The project read MILVUS_URI. pymilvus reads a variable of that exact
        name at import time and requires an http[s]:// address, so setting it
        to the Milvus Lite file path the project's own .env documented raised
        ConnectionConfigException before any project code ran.

  G1·3  has_vectors() and count() read an in-process dict. Vectors persisted;
        the record that they existed did not. A second process saw False for
        an asset whose vectors were in the database, so the API could not tell
        what the worker had embedded and a restarted worker re-embedded
        everything.

These run against real Milvus Lite files, not mocks — the bug was in what the
database actually persisted.
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator

import pytest

from src.infrastructure.vector_store.milvus_vector_store import MilvusVectorStore

_DIM = 4


def _unit(i: int) -> list[float]:
    v = [0.0] * _DIM
    v[i % _DIM] = 1.0
    return v


@pytest.fixture()
def db_path(tmp_path) -> str:
    return str(tmp_path / "erp_rag.db")


@pytest.fixture()
def store(db_path: str) -> Iterator[MilvusVectorStore]:
    yield MilvusVectorStore(uri=db_path, dim=_DIM)


class TestIdempotencySurvivesTheProcess:
    """G1·3 — the marker has to outlive the object that wrote it."""

    def test_a_new_instance_sees_the_completed_asset(self, store, db_path):
        store.upsert("A1", "t1", _unit(0), "c1", "vat rules")
        store.save_vectors("A1", "t1", 1)

        reopened = MilvusVectorStore(uri=db_path, dim=_DIM)
        assert reopened.has_vectors("A1", "t1") is True
        assert reopened.count("A1", "t1") == 1

    def test_a_new_instance_can_still_search_the_vectors(self, store, db_path):
        store.upsert("A1", "t1", _unit(0), "c1", "vat rules")
        store.save_vectors("A1", "t1", 1)

        reopened = MilvusVectorStore(uri=db_path, dim=_DIM)
        hits = reopened.search_similar(query_embedding=_unit(0), k=5, tenant_id="t1")
        assert [h.content for h in hits] == ["vat rules"]

    def test_unknown_asset_is_not_marked(self, store):
        assert store.has_vectors("never-seen", "t1") is False
        assert store.count("never-seen", "t1") == 0

    def test_marker_is_scoped_to_the_tenant(self, store):
        store.upsert("A1", "t1", _unit(0), "c1", "vat rules")
        store.save_vectors("A1", "t1", 1)

        assert store.has_vectors("A1", "other-tenant") is False

    def test_re_saving_replaces_rather_than_accumulates(self, store):
        store.save_vectors("A1", "t1", 2)
        store.save_vectors("A1", "t1", 5)

        assert store.count("A1", "t1") == 5


class TestPartialEmbedIsNotMistakenForDone:
    """The reason count() is not derived from counting chunk rows.

    EmbedAssetUseCase upserts each chunk and calls save_vectors last. If it
    dies half way, rows exist but the asset is not embedded. Deriving
    "done" from row count > 0 would make the use case skip it forever,
    stranding the asset permanently half embedded.
    """

    def test_chunks_present_but_unfinished_reads_as_not_embedded(self, store):
        store.upsert("A1", "t1", _unit(0), "c1", "first chunk")
        store.upsert("A1", "t1", _unit(1), "c2", "second chunk")
        # crash here — save_vectors never runs

        assert store.has_vectors("A1", "t1") is False, (
            "a half-finished embed must not report as done"
        )

    def test_the_rows_really_are_there(self, store):
        """Guards the test above: it must fail for the right reason."""
        store.upsert("A1", "t1", _unit(0), "c1", "first chunk")

        hits = store.search_similar(query_embedding=_unit(0), k=5, tenant_id="t1")
        assert len(hits) == 1

    def test_finishing_the_embed_then_marks_it_done(self, store):
        store.upsert("A1", "t1", _unit(0), "c1", "first chunk")
        assert store.has_vectors("A1", "t1") is False

        store.save_vectors("A1", "t1", 1)
        assert store.has_vectors("A1", "t1") is True


class TestEnvVarCollision:
    """G1·2 — the name pymilvus already owns."""

    def test_pymilvus_rejects_a_file_path_in_its_own_variable(self, tmp_path):
        """Importing pymilvus with MILVUS_URI set to a path is fatal.

        Run in a subprocess: pymilvus parses the variable at import, so it
        cannot be re-tested in a process that already imported it.
        """
        env = {**os.environ, "MILVUS_URI": str(tmp_path / "x.db")}
        proc = subprocess.run(
            [sys.executable, "-c", "import pymilvus"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert proc.returncode != 0
        assert "Illegal uri" in proc.stderr

    def test_our_variable_does_not_collide(self, tmp_path):
        env = {**os.environ, "MILVUS_DB_URI": str(tmp_path / "x.db")}
        env.pop("MILVUS_URI", None)
        proc = subprocess.run(
            [sys.executable, "-c", "import pymilvus"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr

    def test_factory_reads_the_renamed_variable(self, tmp_path, monkeypatch):
        from src.infrastructure.di.factory import _select_vector_store

        monkeypatch.delenv("MILVUS_URI", raising=False)
        monkeypatch.setenv("MILVUS_DB_URI", str(tmp_path / "factory.db"))

        assert isinstance(_select_vector_store(dim=_DIM), MilvusVectorStore)

    def test_factory_ignores_the_old_variable(self, tmp_path, monkeypatch):
        """A leftover MILVUS_URI must not silently re-enable the collision."""
        from src.infrastructure.di.factory import _select_vector_store
        from src.infrastructure.vector_store.in_memory_vector_store import (
            InMemoryVectorStore,
        )

        monkeypatch.setenv("MILVUS_URI", str(tmp_path / "old.db"))
        monkeypatch.delenv("MILVUS_DB_URI", raising=False)

        assert isinstance(_select_vector_store(dim=_DIM), InMemoryVectorStore)


# ---------------------------------------------------------------------------
# Against a Milvus server — Sprint 12 (S12·1)
# ---------------------------------------------------------------------------

MILVUS_SERVER_URI = os.environ.get("MILVUS_TEST_SERVER_URI", "")


@pytest.mark.skipif(
    not MILVUS_SERVER_URI,
    reason="MILVUS_TEST_SERVER_URI not set — needs a running Milvus server",
)
class TestAgainstAMilvusServer:
    """Milvus Lite is a single-process file lock, so the API and a separate
    Celery worker cannot both open it — the worker dies with
    "Open local milvus failed". A server is what makes the two-process topology
    the whole Celery layer exists for actually possible.

    The server also behaves differently in a way Lite hid: it buffers inserts
    and serves queries from a bounded-staleness view, so a marker written by
    one client was invisible to another for a while. Lite applied writes
    immediately, so no amount of single-process testing would have shown it.
    """

    @pytest.fixture()
    def collection(self) -> Iterator[str]:
        import uuid

        name = f"test_{uuid.uuid4().hex[:10]}"
        yield name
        try:
            MilvusVectorStore(
                uri=MILVUS_SERVER_URI, dim=_DIM, collection_name=name
            ).drop()
        except Exception:  # noqa: BLE001 — cleanup must not fail the test
            pass

    def test_a_second_client_sees_the_vectors(self, collection):
        writer = MilvusVectorStore(
            uri=MILVUS_SERVER_URI, dim=_DIM, collection_name=collection
        )
        writer.upsert("A1", "t1", _unit(0), "c1", "vat rules")
        writer.save_vectors("A1", "t1", 1)

        reader = MilvusVectorStore(
            uri=MILVUS_SERVER_URI, dim=_DIM, collection_name=collection
        )
        assert len(reader.search_similar(_unit(0), 5, "t1")) == 1

    def test_a_second_client_sees_the_completion_marker(self, collection):
        """The bug the server exposed: searchable vectors, invisible marker.

        Left unfixed, the worker would re-embed an asset it had just finished
        because has_vectors() answered False from a stale view.
        """
        writer = MilvusVectorStore(
            uri=MILVUS_SERVER_URI, dim=_DIM, collection_name=collection
        )
        writer.upsert("A1", "t1", _unit(0), "c1", "vat rules")
        writer.save_vectors("A1", "t1", 1)

        reader = MilvusVectorStore(
            uri=MILVUS_SERVER_URI, dim=_DIM, collection_name=collection
        )
        assert reader.has_vectors("A1", "t1") is True
        assert reader.count("A1", "t1") == 1

    def test_tenant_scoping_holds_on_the_server(self, collection):
        writer = MilvusVectorStore(
            uri=MILVUS_SERVER_URI, dim=_DIM, collection_name=collection
        )
        writer.upsert("A1", "t1", _unit(0), "c1", "vat rules")
        writer.save_vectors("A1", "t1", 1)

        reader = MilvusVectorStore(
            uri=MILVUS_SERVER_URI, dim=_DIM, collection_name=collection
        )
        assert reader.search_similar(_unit(0), 5, "other-tenant") == []

    def test_the_factory_accepts_a_server_uri(self, monkeypatch):
        from src.infrastructure.di.factory import _select_vector_store

        monkeypatch.setenv("MILVUS_DB_URI", MILVUS_SERVER_URI)

        assert isinstance(_select_vector_store(dim=_DIM), MilvusVectorStore)
