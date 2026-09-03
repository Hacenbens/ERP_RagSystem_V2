"""MilvusVectorStore — production VectorStorePort backed by Milvus.

Uses the pymilvus MilvusClient high-level API (pymilvus >= 2.4).

URI conventions:
  - "/path/to/file.db"         → Milvus Lite (local file, no server required)
  - "http://host:19530"        → full Milvus server (production)

The collection is created automatically on first use with:
  - COSINE metric (scores range −1 … 1; higher = more similar)
  - FLAT index (exact search; swap to HNSW for large collections)
  - Explicit schema: chunk_id, asset_id, tenant_id, erp_module, content, embedding

Tenant isolation is enforced at query time via a Milvus filter expression.

Two collections are used:

  erp_rag_chunks        one row per embedded chunk (the searchable vectors)
  erp_rag_embed_state   one row per (asset_id, tenant_id) recording that the
                        asset finished embedding, and how many vectors it
                        produced

The second exists because idempotency has to survive the process. It was an
in-process dict, so has_vectors() answered False for an asset whose vectors
were sitting in the database: the API could not see what the worker had
embedded, and a restarted worker re-embedded everything.

Deriving the answer by counting chunk rows would be simpler but wrong. A run
that dies half way leaves rows behind, so count > 0 would report the asset as
done and EmbedAssetUseCase would skip it forever, stranding it half embedded.
The marker is written only after the last chunk lands, so it means finished,
not started.
"""
from __future__ import annotations

from typing import Any

from pymilvus import DataType, MilvusClient

from src.domain.models.scored_chunk import ScoredChunk
from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_DEFAULT_COLLECTION = "erp_rag_chunks"
_STATE_SUFFIX = "_embed_state"
_CONTENT_MAX_LEN = 32_000  # Milvus VARCHAR practical limit for chunk text


class MilvusVectorStore(VectorStorePort):
    """Milvus-backed vector store for RAG retrieval.

    Args:
        uri: Milvus connection string (file path for Lite, URL for server).
        collection_name: Milvus collection name (default: ``erp_rag_chunks``).
        dim: Embedding dimension (default: 768).
    """

    def __init__(
        self,
        uri: str,
        collection_name: str = _DEFAULT_COLLECTION,
        dim: int = 768,
    ) -> None:
        self._uri = uri
        self._collection = collection_name
        self._state_collection = f"{collection_name}{_STATE_SUFFIX}"
        self._dim = dim
        self._client = MilvusClient(uri)
        self._ensure_collection()
        self._ensure_state_collection()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_collection(self) -> None:
        """Create collection + FLAT/COSINE index if it does not already exist."""
        if self._client.has_collection(self._collection):
            return

        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=256)
        schema.add_field("asset_id", DataType.VARCHAR, max_length=256)
        schema.add_field("tenant_id", DataType.VARCHAR, max_length=256)
        schema.add_field("erp_module", DataType.VARCHAR, max_length=64)
        schema.add_field("content", DataType.VARCHAR, max_length=_CONTENT_MAX_LEN)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self._dim)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="FLAT",
            metric_type="COSINE",
        )

        self._client.create_collection(
            self._collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info(
            "milvus_vector_store.collection_created",
            collection=self._collection,
            dim=self._dim,
            uri=self._uri,
        )

    def _ensure_state_collection(self) -> None:
        """Create the embed-state collection if it does not already exist.

        Milvus requires every collection to declare a vector field, and rejects
        a dimension below 2, so this one carries a 2-dimension placeholder that
        is never searched. The rows are addressed by filter only.
        """
        if self._client.has_collection(self._state_collection):
            return

        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("asset_id", DataType.VARCHAR, max_length=256)
        schema.add_field("tenant_id", DataType.VARCHAR, max_length=256)
        schema.add_field("vector_count", DataType.INT64)
        schema.add_field("placeholder", DataType.FLOAT_VECTOR, dim=2)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="placeholder",
            index_type="FLAT",
            metric_type="COSINE",
        )
        self._client.create_collection(
            self._state_collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info(
            "milvus_vector_store.state_collection_created",
            collection=self._state_collection,
        )

    def _asset_filter(self, asset_id: str, tenant_id: str) -> str:
        """Filter expression addressing one asset within one tenant."""
        return f'asset_id == "{asset_id}" and tenant_id == "{tenant_id}"'

    def _build_filter(self, tenant_id: str, erp_module: str | None) -> str:
        """Compose a Milvus filter expression from tenant_id and optional erp_module."""
        filt = f'tenant_id == "{tenant_id}"'
        if erp_module is not None:
            filt += f' and erp_module == "{erp_module}"'
        return filt

    # ------------------------------------------------------------------
    # VectorStorePort — idempotency tracking
    # ------------------------------------------------------------------

    def has_vectors(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if this asset finished embedding, in any process.

        Reads the durable marker, so a worker restart or a second process sees
        the same answer.
        """
        return self.count(asset_id, tenant_id) > 0

    def save_vectors(self, asset_id: str, tenant_id: str, vector_count: int) -> None:
        """Mark the asset finished and record how many vectors it produced.

        Replaces any previous marker so a re-embed does not accumulate rows.
        """
        self._client.delete(
            self._state_collection,
            filter=self._asset_filter(asset_id, tenant_id),
        )
        self._client.insert(
            self._state_collection,
            data=[{
                "asset_id": asset_id,
                "tenant_id": tenant_id,
                "vector_count": vector_count,
                "placeholder": [0.0, 0.0],
            }],
        )
        logger.debug(
            "milvus_vector_store.embed_state_saved",
            asset_id=asset_id,
            tenant_id=tenant_id,
            vector_count=vector_count,
        )

    def count(self, asset_id: str, tenant_id: str) -> int:
        """Return the recorded vector count, or 0 if never finished embedding."""
        rows = self._client.query(
            self._state_collection,
            filter=self._asset_filter(asset_id, tenant_id),
            output_fields=["vector_count"],
        )
        if not rows:
            return 0
        return int(rows[0]["vector_count"])

    # ------------------------------------------------------------------
    # VectorStorePort — vector operations
    # ------------------------------------------------------------------

    def upsert(
        self,
        asset_id: str,
        tenant_id: str,
        embedding: list[float],
        chunk_id: str,
        content: str,
        erp_module: str | None = None,
    ) -> None:
        """Store or replace the embedding for a single chunk (idempotent).

        Deletes any existing record with the same chunk_id + tenant_id before
        inserting, so repeated calls for the same chunk do not create duplicates.
        """
        # Delete stale record if present (makes the operation idempotent)
        self._client.delete(
            self._collection,
            filter=f'chunk_id == "{chunk_id}" and tenant_id == "{tenant_id}"',
        )

        truncated = content[:_CONTENT_MAX_LEN]
        if len(content) > _CONTENT_MAX_LEN:
            logger.warning(
                "milvus_vector_store.content_truncated",
                chunk_id=chunk_id,
                original_len=len(content),
                stored_len=_CONTENT_MAX_LEN,
            )

        self._client.insert(
            self._collection,
            data=[{
                "chunk_id": chunk_id,
                "asset_id": asset_id,
                "tenant_id": tenant_id,
                "erp_module": erp_module or "",
                "content": truncated,
                "embedding": embedding,
            }],
        )
        logger.debug(
            "milvus_vector_store.upserted",
            chunk_id=chunk_id,
            asset_id=asset_id,
            tenant_id=tenant_id,
        )

    def search_similar(
        self,
        query_embedding: list[float],
        k: int,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> list[ScoredChunk]:
        """Return the top-k chunks most similar to query_embedding.

        Scoped to tenant_id; optionally filtered by erp_module.
        Results are ordered by descending COSINE similarity score.
        """
        filt = self._build_filter(tenant_id, erp_module)

        raw: list[list[dict[str, Any]]] = self._client.search(
            self._collection,
            data=[query_embedding],
            filter=filt,
            limit=k,
            output_fields=["chunk_id", "asset_id", "content", "erp_module"],
        )

        if not raw or not raw[0]:
            return []

        results: list[ScoredChunk] = []
        for hit in raw[0]:
            entity = hit["entity"]
            module_val: str = entity.get("erp_module", "") or ""
            results.append(
                ScoredChunk(
                    chunk_id=entity["chunk_id"],
                    content=entity["content"],
                    score=float(hit["distance"]),
                    source=entity["asset_id"],
                    erp_module=module_val if module_val else None,
                )
            )

        logger.info(
            "milvus_vector_store.search_done",
            tenant_id=tenant_id,
            erp_module=erp_module,
            k=k,
            returned=len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Test / maintenance helpers
    # ------------------------------------------------------------------

    def drop(self) -> None:
        """Drop both collections. Use in tests only."""
        self._client.drop_collection(self._collection)
        self._client.drop_collection(self._state_collection)
        logger.info("milvus_vector_store.collection_dropped", collection=self._collection)


__all__ = ["MilvusVectorStore"]
