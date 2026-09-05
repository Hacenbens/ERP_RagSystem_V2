"""
Port: VectorDBProviderPort — a driver-level contract for a vector database.

This sits below VectorStorePort, not beside it. VectorStorePort expresses what
the use cases need (has this asset been embedded, retrieve chunks for a query);
this expresses what a vector database *is* — connect, manage collections,
insert, search. A provider implements this; VectorStorePort is implemented on
top of it.

Keeping them apart means adding Qdrant or pgvector is one new class here, with
no change to EmbedAssetUseCase or VectorRetriever.

Tenant isolation
----------------
Each tenant gets its own collection, named by ``tenant_collection()``. That is
a stronger guarantee than filtering one shared collection by a tenant_id field:
a forgotten filter returns another tenant's rows, whereas a wrong collection
name returns nothing. The SQL side of this system had exactly that bug — a
literal tenant that bypassed the filter and read across tenants.

The trade-off is real and worth stating: collections are not free. Milvus holds
per-collection metadata and index structures, and while the hard ceiling is
large, performance degrades well before it. This design suits tens to low
thousands of tenants. Beyond that, a shared collection with a partition key is
the scalable shape, and this port would need a different implementation rather
than a different caller.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.domain.models.vector_records import (
    CollectionInfo,
    VectorRecord,
    VectorSearchHit,
)


class VectorDBProviderPort(ABC):
    """Connect to a vector database and manage collections, records and search."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """Establish the connection.

        For a file-backed provider this opens the local path; for a served one
        it dials the endpoint. Calling it twice is a no-op rather than an
        error — a caller should not have to track whether it already connected.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection and release the client.

        Safe to call when not connected, for the same reason.
        """

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    @abstractmethod
    def is_collection_exists(self, collection_name: str) -> bool:
        """Return True if the collection exists."""

    @abstractmethod
    def list_collections(self) -> list[str]:
        """Return the names of all collections, sorted."""

    @abstractmethod
    def get_collection_info(self, collection_name: str) -> CollectionInfo:
        """Return structural metadata, including the record count.

        Raises:
            CollectionNotFoundError: no such collection. Absent is different
                from empty, and the caller usually needs to tell them apart.
        """

    @abstractmethod
    def create_collection(
        self,
        collection_name: str,
        embedding_size: int,
        do_recreate: bool = False,
    ) -> None:
        """Create a collection for vectors of ``embedding_size`` dimensions.

        Args:
            do_recreate: drop an existing collection of the same name first.
                Destroys every record in it — the default is False so that
                losing data requires asking for it. Without the flag, creating
                over an existing collection is a no-op, which makes startup
                idempotent for two workers racing to create the same one.
        """

    @abstractmethod
    def delete_collection(self, collection_name: str) -> None:
        """Drop the collection and all its vectors. A no-op if absent."""

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @abstractmethod
    def insert_one(
        self,
        collection_name: str,
        text: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> str:
        """Insert one record and return its id.

        Passing an existing ``record_id`` replaces that record rather than
        adding a duplicate, so a retried embed job converges instead of
        accumulating copies. A generated id is returned when none is given.
        """

    @abstractmethod
    def insert_many(
        self,
        collection_name: str,
        texts: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
        record_ids: list[str] | None = None,
        batch_size: int = 50,
    ) -> list[str]:
        """Insert many records in batches, returning their ids in order.

        Raises:
            ValueError: the parallel lists differ in length. Silently zipping
                to the shortest would attach vectors to the wrong text.
        """

    @abstractmethod
    def get_record(self, collection_name: str, record_id: str) -> VectorRecord | None:
        """Return the record with that id, or None if it is not there.

        Retrieval by primary key, which every vector database supports. It is
        what lets a caller ask a yes/no question about one known record —
        "did this asset finish embedding" — without a similarity search that
        would answer a different question.
        """

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @abstractmethod
    def search_by_vector(
        self,
        collection_name: str,
        vector: list[float],
        limit: int = 10,
    ) -> list[VectorSearchHit]:
        """Return up to ``limit`` nearest records, most similar first.

        An absent collection yields an empty list rather than raising: a tenant
        who has uploaded nothing is a normal state, not an error.
        """

    # ------------------------------------------------------------------
    # Tenancy
    # ------------------------------------------------------------------

    @abstractmethod
    def tenant_collection(self, tenant_id: str) -> str:
        """Return the collection name that holds *tenant_id*'s vectors.

        Deterministic, so any process resolves a tenant to the same collection
        without shared state.
        """

    @abstractmethod
    def search_by_tenant(
        self,
        tenant_id: str,
        vector: list[float],
        limit: int = 10,
    ) -> list[VectorSearchHit]:
        """Search only within *tenant_id*'s collection.

        Reaching another tenant's data would require naming their collection
        explicitly, which no caller has reason to construct.
        """


class VectorDBError(RuntimeError):
    """Base for vector database failures."""


class CollectionNotFoundError(VectorDBError):
    """The named collection does not exist."""


__all__ = [
    "CollectionNotFoundError",
    "VectorDBError",
    "VectorDBProviderPort",
]
