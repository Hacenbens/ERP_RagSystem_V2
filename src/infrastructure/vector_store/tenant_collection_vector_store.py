"""
TenantCollectionVectorStore — VectorStorePort over a VectorDBProviderPort,
with one collection per tenant.

Replaces the single shared ``erp_rag_chunks`` collection filtered by a
``tenant_id`` field. A forgotten filter there returns another tenant's rows;
a wrong collection name returns nothing. The SQL side of this system shipped
exactly that bug — a literal tenant that bypassed the filter — so the isolation
is moved into the storage layout rather than left to every query getting it
right.

Connection ownership
--------------------
This class never opens or closes a connection. It receives a provider that is
already connected and only ever calls data operations on it. Lifecycle belongs
to the provider alone, and the DI factory is what drives it: build the
provider, connect it, then construct this store around it.

That is deliberate. A store that could reconnect would let a connection be
opened from wherever a query happened to run — in a Celery fork, mid-request,
inside a retry — with nothing owning when it closes. One owner, one place.
"""
from __future__ import annotations

from src.domain.models.scored_chunk import ScoredChunk
from src.domain.ports.vector_db_provider_port import VectorDBProviderPort
from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# Embed-state markers live in a sibling collection so they never appear in
# search results. Milvus requires every collection to declare a vector field
# and rejects a dimension below 2, hence a 2-element placeholder that is never
# searched — the rows are addressed by id.
_STATE_SUFFIX = "_state"
_STATE_PLACEHOLDER_VECTOR = [0.0, 0.0]

# erp_module narrows results within a tenant. It is a relevance filter, not a
# security boundary — the tenant boundary is the collection itself — so it is
# applied after retrieval rather than pushed into the driver, which would mean
# teaching every provider a filter dialect. Over-fetching keeps the filtered
# result from collapsing below k when a tenant holds several modules.
_MODULE_OVERFETCH = 4


class TenantCollectionVectorStore(VectorStorePort):
    """Store and search chunk vectors, one collection per tenant.

    Args:
        provider: an already-connected VectorDBProviderPort. This class does
            not connect it and will not disconnect it.
        embedding_size: dimension collections are created with.
    """

    def __init__(
        self,
        provider: VectorDBProviderPort,
        embedding_size: int = 768,
    ) -> None:
        self._provider = provider
        self._embedding_size = embedding_size

    # ------------------------------------------------------------------
    # Collection naming
    # ------------------------------------------------------------------

    def _chunks(self, tenant_id: str) -> str:
        return self._provider.tenant_collection(tenant_id)

    def _state(self, tenant_id: str) -> str:
        return f"{self._provider.tenant_collection(tenant_id)}{_STATE_SUFFIX}"

    # ------------------------------------------------------------------
    # VectorStorePort — idempotency tracking
    # ------------------------------------------------------------------

    def has_vectors(self, asset_id: str, tenant_id: str) -> bool:
        """Return True if this asset finished embedding, in any process."""
        return self.count(asset_id, tenant_id) > 0

    def save_vectors(self, asset_id: str, tenant_id: str, vector_count: int) -> None:
        """Mark the asset finished and record how many vectors it produced.

        Written only after the last chunk lands, so it means finished rather
        than started. Deriving completion from a chunk count instead would let
        a run that died half way read as done and be skipped forever.
        """
        self._provider.insert_one(
            self._state(tenant_id),
            text=asset_id,
            vector=list(_STATE_PLACEHOLDER_VECTOR),
            metadata={"asset_id": asset_id, "vector_count": int(vector_count)},
            record_id=asset_id,
        )
        logger.debug(
            "tenant_vector_store.embed_state_saved",
            asset_id=asset_id,
            tenant_id=tenant_id,
            vector_count=vector_count,
        )

    def count(self, asset_id: str, tenant_id: str) -> int:
        """Return the recorded vector count, or 0 if never finished embedding."""
        record = self._provider.get_record(self._state(tenant_id), asset_id)
        if record is None:
            return 0
        return int(record.metadata.get("vector_count", 0))

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
        """Store or replace one chunk's vector in the tenant's collection.

        Keyed by chunk_id, so re-running an embed converges on the same
        records instead of accumulating a duplicate of every chunk.
        """
        self._provider.insert_one(
            self._chunks(tenant_id),
            text=content,
            vector=embedding,
            metadata={
                "asset_id": asset_id,
                "erp_module": erp_module or "",
                "chunk_id": chunk_id,
            },
            record_id=chunk_id,
        )

    def search_similar(
        self,
        query_embedding: list[float],
        k: int,
        tenant_id: str,
        erp_module: str | None = None,
    ) -> list[ScoredChunk]:
        """Return the top-k chunks for this tenant, most similar first.

        Only the tenant's own collection is searched, so cross-tenant results
        are not filtered out — they are never fetched.
        """
        limit = k * _MODULE_OVERFETCH if erp_module else k
        hits = self._provider.search_by_tenant(tenant_id, query_embedding, limit=limit)

        chunks: list[ScoredChunk] = []
        for hit in hits:
            module = hit.metadata.get("erp_module") or None
            if erp_module is not None and module != erp_module:
                continue
            chunks.append(
                ScoredChunk(
                    chunk_id=hit.metadata.get("chunk_id") or hit.record_id,
                    content=hit.text,
                    score=hit.score,
                    source=hit.metadata.get("asset_id", ""),
                    erp_module=module,
                )
            )
            if len(chunks) == k:
                break

        logger.info(
            "tenant_vector_store.search_done",
            tenant_id=tenant_id,
            erp_module=erp_module,
            k=k,
            returned=len(chunks),
        )
        return chunks

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def drop_tenant(self, tenant_id: str) -> None:
        """Delete everything belonging to one tenant.

        Per-tenant collections make this two drops rather than a filtered
        delete over shared storage — which matters when the request is a
        legal one to erase a customer's data.
        """
        self._provider.delete_collection(self._chunks(tenant_id))
        self._provider.delete_collection(self._state(tenant_id))
        logger.info("tenant_vector_store.tenant_dropped", tenant_id=tenant_id)


__all__ = ["TenantCollectionVectorStore"]
