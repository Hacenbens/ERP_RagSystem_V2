"""
Fail-fast database validation at worker startup — Sprint 11 (G1·4).

pymongo connects lazily, so MongoClient(uri) succeeds against a wrong host, a
wrong port and wrong credentials alike. build_worker_container() therefore
built cleanly and every Celery task failed later at runtime:

    OperationFailure: Command delete requires authentication (code 13)

which is the opposite of the fail-fast the DI container exists to provide — an
operator sees a healthy worker quietly dead-lettering everything.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.di.factory import (
    MongoUnavailableError,
    build_worker_container,
)
from src.infrastructure.persistence.chunk_store import InMemoryChunkStore
from src.infrastructure.workers.dead_letter_repository import (
    InMemoryDeadLetterRepository,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """build_worker_container is cached behind a module-level singleton."""
    import src.infrastructure.di.factory as factory

    factory._worker_container = None
    yield
    factory._worker_container = None


class TestUnreachableDatabaseFailsAtStartup:
    def test_connection_refused_raises_at_build_time(self, monkeypatch):
        monkeypatch.setenv("MONGODB_URI", "mongodb://127.0.0.1:27099")

        with pytest.raises(MongoUnavailableError):
            build_worker_container()

    def test_the_error_names_the_variable_to_fix(self, monkeypatch):
        monkeypatch.setenv("MONGODB_URI", "mongodb://127.0.0.1:27099")

        with pytest.raises(MongoUnavailableError, match="MONGODB_URI"):
            build_worker_container()

    def test_the_error_mentions_credentials(self, monkeypatch):
        """The observed failure was auth, so the message has to point at it."""
        monkeypatch.setenv("MONGODB_URI", "mongodb://127.0.0.1:27099")

        with pytest.raises(MongoUnavailableError, match="credentials"):
            build_worker_container()


class TestTheProbeExercisesAuthentication:
    """A ping is not enough: it answers on a server that rejects real work."""

    def test_probe_reads_the_erp_rag_database(self, monkeypatch):
        monkeypatch.setenv("MONGODB_URI", "mongodb://ignored:27017")
        fake = MagicMock()

        with patch("pymongo.MongoClient", return_value=fake):
            build_worker_container()

        fake.__getitem__.assert_any_call("erp_rag")
        fake.__getitem__.return_value.list_collection_names.assert_called_once()

    def test_the_container_connects_only_once(self, monkeypatch):
        """The user repository and the worker stores share one connection."""
        monkeypatch.setenv("MONGODB_URI", "mongodb://ignored:27017")

        with patch("pymongo.MongoClient", return_value=MagicMock()) as client:
            build_worker_container()

        assert client.call_count == 1

    def test_an_auth_error_from_the_probe_fails_the_build(self, monkeypatch):
        from pymongo.errors import OperationFailure

        monkeypatch.setenv("MONGODB_URI", "mongodb://ignored:27017")
        fake = MagicMock()
        fake.__getitem__.return_value.list_collection_names.side_effect = (
            OperationFailure("Command listCollections requires authentication")
        )

        with patch("pymongo.MongoClient", return_value=fake):
            with pytest.raises(MongoUnavailableError, match="authentication"):
                build_worker_container()


class TestInMemoryFallbackIsUnaffected:
    """No MONGODB_URI means no database to validate — CI depends on this."""

    def test_blank_uri_builds_with_in_memory_stores(self, monkeypatch):
        monkeypatch.delenv("MONGODB_URI", raising=False)

        container = build_worker_container()

        assert isinstance(container.get("chunk_store"), InMemoryChunkStore)
        assert isinstance(
            container.get("dead_letter_repository"), InMemoryDeadLetterRepository
        )

    def test_blank_uri_does_not_touch_pymongo(self, monkeypatch):
        monkeypatch.delenv("MONGODB_URI", raising=False)

        with patch("pymongo.MongoClient") as client:
            build_worker_container()

        client.assert_not_called()
