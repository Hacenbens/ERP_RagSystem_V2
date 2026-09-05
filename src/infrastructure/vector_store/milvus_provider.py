"""
MilvusVectorDBProvider — VectorDBProviderPort backed by Milvus.

Works against a Milvus server (``http://host:19530``) or Milvus Lite (a local
``.db`` path). Lite holds a single-process file lock, so anything running an API
and a worker needs the server.

One collection per tenant. Names are derived by ``tenant_collection()`` rather
than used raw: Milvus rejects hyphens, rejects a leading digit, and caps the
length, so a tenant id like ``tenant-ferza`` is not a legal collection name.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from pymilvus import DataType, MilvusClient

from src.domain.models.vector_records import (
    CollectionInfo,
    VectorRecord,
    VectorSearchHit,
)
from src.domain.ports.vector_db_provider_port import (
    CollectionNotFoundError,
    VectorDBProviderPort,
)
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_TEXT_MAX_LEN = 32_000
_ID_MAX_LEN = 128
_METADATA_MAX_LEN = 8_192

# Milvus: letters, digits and underscores only, and the first character may not
# be a digit. 255 is the documented ceiling; the prefix and hash are budgeted
# out of it so the readable part is what gets truncated.
_COLLECTION_PREFIX = "erp_t_"
_HASH_LEN = 10
_MAX_COLLECTION_LEN = 200
_ILLEGAL_CHARS = re.compile(r"[^a-zA-Z0-9_]")


class MilvusVectorDBProvider(VectorDBProviderPort):
    """Milvus-backed vector database provider.

    Args:
        uri: ``http://host:19530`` for a server, or a ``.db`` path for Lite.
        default_embedding_size: dimension used when a collection is created
            implicitly, e.g. on the first insert for a new tenant.
        auto_connect: connect on construction. Set False to control when the
            connection is opened — a worker that builds its container at import
            time should not dial the database then.
        consistency_level: how fresh reads must be. Defaults to "Strong"
            because this system's defining interaction is upload a document,
            then ask about it. Milvus serves searches from a bounded-staleness
            view by default, so a chunk written moments ago is not yet
            findable — and the user sees "not grounded", indistinguishable from
            the document not containing the answer. Collections here are
            per-tenant and small; correctness after write is worth more than
            the latency. Set "Bounded" if a tenant's corpus grows large enough
            for that to reverse.
    """

    def __init__(
        self,
        uri: str,
        default_embedding_size: int = 768,
        auto_connect: bool = True,
        consistency_level: str = "Strong",
    ) -> None:
        self._uri = uri
        self._default_embedding_size = default_embedding_size
        self._consistency_level = consistency_level
        self._client: MilvusClient | None = None
        if auto_connect:
            self.connect()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the connection. Idempotent."""
        if self._client is not None:
            return
        self._client = MilvusClient(self._uri)
        logger.info("milvus_provider.connected", uri=self._uri)

    def disconnect(self) -> None:
        """Close the connection. Idempotent."""
        if self._client is None:
            return
        try:
            self._client.close()
        except Exception as exc:  # noqa: BLE001 — closing must not raise
            logger.warning("milvus_provider.close_failed", error=str(exc))
        finally:
            self._client = None
            logger.info("milvus_provider.disconnected", uri=self._uri)

    @property
    def _c(self) -> MilvusClient:
        """The client, connecting first if a caller skipped connect()."""
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def is_collection_exists(self, collection_name: str) -> bool:
        """Return True if the collection exists."""
        return bool(self._c.has_collection(collection_name))

    def list_collections(self) -> list[str]:
        """Return every collection name, sorted."""
        return sorted(self._c.list_collections())

    def get_collection_info(self, collection_name: str) -> CollectionInfo:
        """Return the record count and, where reported, the vector dimension."""
        if not self.is_collection_exists(collection_name):
            raise CollectionNotFoundError(f"No such collection: {collection_name!r}")

        rows = self._c.query(
            collection_name,
            filter="",
            output_fields=["count(*)"],
            consistency_level="Strong",
        )
        count = int(rows[0]["count(*)"]) if rows else 0

        embedding_size: int | None = None
        try:
            for field in self._c.describe_collection(collection_name).get("fields", []):
                if field.get("name") == "vector":
                    embedding_size = (field.get("params") or {}).get("dim")
        except Exception as exc:  # noqa: BLE001 — metadata is best-effort
            logger.debug("milvus_provider.describe_failed", error=str(exc))

        return CollectionInfo(
            name=collection_name,
            record_count=count,
            embedding_size=int(embedding_size) if embedding_size else None,
        )

    def create_collection(
        self,
        collection_name: str,
        embedding_size: int,
        do_recreate: bool = False,
    ) -> None:
        """Create the collection, optionally dropping an existing one first."""
        if self.is_collection_exists(collection_name):
            if not do_recreate:
                return
            logger.warning(
                "milvus_provider.recreating_collection",
                collection=collection_name,
                note="every record in it is being dropped",
            )
            self.delete_collection(collection_name)

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("record_id", DataType.VARCHAR, max_length=_ID_MAX_LEN,
                         is_primary=True)
        schema.add_field("text", DataType.VARCHAR, max_length=_TEXT_MAX_LEN)
        # Metadata is stored as a JSON string rather than a JSON field so the
        # same schema works on Milvus Lite, which does not support DataType.JSON.
        schema.add_field("metadata", DataType.VARCHAR, max_length=_METADATA_MAX_LEN)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=embedding_size)

        index_params = self._c.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="FLAT",   # exact search; swap to HNSW as collections grow
            metric_type="COSINE",
        )
        self._c.create_collection(collection_name, schema=schema,
                                  index_params=index_params)
        logger.info(
            "milvus_provider.collection_created",
            collection=collection_name,
            embedding_size=embedding_size,
        )

    def delete_collection(self, collection_name: str) -> None:
        """Drop the collection. A no-op when it does not exist."""
        if not self.is_collection_exists(collection_name):
            return
        self._c.drop_collection(collection_name)
        logger.info("milvus_provider.collection_dropped", collection=collection_name)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert_one(
        self,
        collection_name: str,
        text: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> str:
        """Insert or replace one record, returning its id."""
        ids = self.insert_many(
            collection_name,
            texts=[text],
            vectors=[vector],
            metadatas=[metadata or {}],
            record_ids=[record_id] if record_id is not None else None,
        )
        return ids[0]

    def insert_many(
        self,
        collection_name: str,
        texts: list[str],
        vectors: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
        record_ids: list[str] | None = None,
        batch_size: int = 50,
    ) -> list[str]:
        """Insert records in batches of ``batch_size``, returning their ids."""
        if len(texts) != len(vectors):
            raise ValueError(
                f"texts and vectors differ in length ({len(texts)} vs "
                f"{len(vectors)}) — zipping them would pair each text with the "
                "wrong vector"
            )
        if metadatas is not None and len(metadatas) != len(texts):
            raise ValueError(
                f"metadatas has {len(metadatas)} entries for {len(texts)} texts"
            )
        if record_ids is not None and len(record_ids) != len(texts):
            raise ValueError(
                f"record_ids has {len(record_ids)} entries for {len(texts)} texts"
            )
        if not texts:
            return []

        self.create_collection(collection_name, len(vectors[0]))

        ids = list(record_ids) if record_ids is not None else [
            str(uuid4()) for _ in texts
        ]
        metas = list(metadatas) if metadatas is not None else [{} for _ in texts]

        rows = [
            {
                "record_id": rid[:_ID_MAX_LEN],
                "text": text[:_TEXT_MAX_LEN],
                "metadata": json.dumps(meta, default=str)[:_METADATA_MAX_LEN],
                "vector": vec,
            }
            for rid, text, vec, meta in zip(ids, texts, vectors, metas, strict=True)
        ]

        # upsert, not insert: a retried embed job must converge on the same
        # records rather than accumulate duplicates of every chunk.
        for start in range(0, len(rows), max(1, batch_size)):
            self._c.upsert(collection_name, data=rows[start:start + batch_size])

        logger.info(
            "milvus_provider.inserted",
            collection=collection_name,
            record_count=len(rows),
            batch_size=batch_size,
        )
        return ids

    def get_record(self, collection_name: str, record_id: str) -> VectorRecord | None:
        """Fetch one record by primary key, at Strong consistency.

        Strong because callers use this to decide whether work is already
        done. A stale "not found" makes a worker redo an embed it just
        finished.
        """
        if not self.is_collection_exists(collection_name):
            return None

        rows = self._c.query(
            collection_name,
            filter=f'record_id == "{record_id}"',
            output_fields=["record_id", "text", "metadata"],
            limit=1,
            consistency_level="Strong",
        )
        if not rows:
            return None
        row = rows[0]
        return VectorRecord(
            record_id=row.get("record_id", ""),
            text=row.get("text", ""),
            metadata=self._decode_metadata(row.get("metadata")),
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_by_vector(
        self,
        collection_name: str,
        vector: list[float],
        limit: int = 10,
    ) -> list[VectorSearchHit]:
        """Return the nearest records, most similar first."""
        if not self.is_collection_exists(collection_name):
            # A tenant who has uploaded nothing yet is a normal state.
            return []

        raw = self._c.search(
            collection_name,
            data=[vector],
            limit=limit,
            output_fields=["record_id", "text", "metadata"],
            consistency_level=self._consistency_level,
        )
        if not raw or not raw[0]:
            return []

        hits: list[VectorSearchHit] = []
        for hit in raw[0]:
            entity = hit.get("entity", {})
            hits.append(
                VectorSearchHit(
                    record_id=entity.get("record_id", ""),
                    text=entity.get("text", ""),
                    score=float(hit.get("distance", 0.0)),
                    metadata=self._decode_metadata(entity.get("metadata")),
                )
            )
        return hits

    @staticmethod
    def _decode_metadata(raw: Any) -> dict[str, Any]:
        """Decode the stored metadata, tolerating anything unparseable."""
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    # ------------------------------------------------------------------
    # Tenancy
    # ------------------------------------------------------------------

    def tenant_collection(self, tenant_id: str) -> str:
        """Return the collection name holding *tenant_id*'s vectors.

        Milvus rejects hyphens and a leading digit and caps the length, so the
        raw tenant id is rarely legal. Sanitising alone is not enough either:
        "acme-eu" and "acme_eu" would both become "acme_eu" and silently share
        one collection. A hash of the original id is appended so distinct
        tenants always get distinct collections, whatever their ids look like.
        """
        digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:_HASH_LEN]
        readable = _ILLEGAL_CHARS.sub("_", tenant_id).lower()
        budget = _MAX_COLLECTION_LEN - len(_COLLECTION_PREFIX) - _HASH_LEN - 1
        return f"{_COLLECTION_PREFIX}{readable[:budget]}_{digest}"

    def search_by_tenant(
        self,
        tenant_id: str,
        vector: list[float],
        limit: int = 10,
    ) -> list[VectorSearchHit]:
        """Search only within *tenant_id*'s own collection."""
        return self.search_by_vector(
            self.tenant_collection(tenant_id), vector, limit=limit
        )


__all__ = ["MilvusVectorDBProvider"]
