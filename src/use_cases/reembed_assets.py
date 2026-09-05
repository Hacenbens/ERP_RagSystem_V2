"""
Use case: ReembedAssetsUseCase — reconcile the chunk store against the vectors.

Chunks are written by the ingest task and vectors by the embed task, so
anything that stops between them leaves an asset whose text is stored and whose
meaning is not searchable. The asset looks ingested. It answers no questions.

Causes seen in this project, all of them silent:

  - the embed task was never registered, so nothing consumed the queue
  - the worker restarted mid-embed, leaving some chunks vectorised
  - retrieval moved to per-tenant collections, so vectors written under the
    old shared layout are no longer where the store looks

The last one is why this exists. A layout change does not corrupt anything; it
relocates where "embedded" is recorded, and every asset embedded before it
quietly stops being findable.

What it does not do
-------------------
It re-embeds from **chunks**, not from source documents. Chunking is therefore
not repeated, which is the point: re-chunking could split text differently and
produce chunk ids that no longer match anything already cited. If a chunking
strategy changed, re-ingest the asset instead.

Known limitation
----------------
It enumerates from the **chunk store**, so it cannot see the mirror-image
defect: a completion marker for an asset whose chunks are gone. Such an asset
keeps returning stale vectors and is never re-ingested, but finding it would
need the vector store to enumerate its own markers, which VectorStorePort
deliberately does not offer — every method there is addressed by a known
(asset_id, tenant_id).

That capability is not added on speculation. No such asset exists in this
system, and an enum member nothing can produce is precisely the kind of thing
ADR-001 exists to keep out. When one turns up, the fix is to add enumeration to
the port and a state alongside MISSING and MISMATCHED.
"""
from __future__ import annotations

from src.domain.models.embedding_consistency import (
    AssetConsistency,
    AssetEmbedState,
    AssetRef,
    ReembedOutcome,
    ReembedReport,
)
from src.domain.ports.chunk_store_port import ChunkStorePort
from src.domain.ports.vector_store_port import VectorStorePort
from src.observability.structured_logger import get_logger
from src.use_cases.tasks.embed_asset_use_case import EmbedAssetUseCase

logger = get_logger(__name__)

_TASK_ID = "reembed-reconciliation"


class ReembedAssetsUseCase:
    """Find assets whose vectors do not match their chunks, and rebuild them.

    Args:
        chunk_store:  source of truth for what was ingested.
        vector_store: what is currently searchable.
        embed_uc:     does the actual embedding. Reused rather than
            reimplemented so re-embedding cannot drift from normal embedding —
            same chunk loop, same metadata, same completion marker written last.
    """

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        vector_store: VectorStorePort,
        embed_uc: EmbedAssetUseCase,
    ) -> None:
        self._chunks = chunk_store
        self._vectors = vector_store
        self._embed = embed_uc

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def inspect(self, tenant_id: str | None = None) -> list[AssetConsistency]:
        """Compare both stores for every asset, without changing anything."""
        refs = self._chunks.list_assets()
        if tenant_id is not None:
            refs = [r for r in refs if r.tenant_id == tenant_id]

        return [self._compare(ref) for ref in sorted(refs, key=lambda r: (r.tenant_id, r.asset_id))]

    def _compare(self, ref: AssetRef) -> AssetConsistency:
        chunk_count = len(self._chunks.find_by_asset(ref.asset_id, ref.tenant_id))
        vector_count = self._vectors.count(ref.asset_id, ref.tenant_id)

        if vector_count == 0:
            state = AssetEmbedState.MISSING
        elif vector_count != chunk_count:
            state = AssetEmbedState.MISMATCHED
        else:
            state = AssetEmbedState.CONSISTENT

        return AssetConsistency(
            ref=ref,
            chunk_count=chunk_count,
            vector_count=vector_count,
            state=state,
        )

    # ------------------------------------------------------------------
    # Repair
    # ------------------------------------------------------------------

    def execute(
        self,
        *,
        tenant_id: str | None = None,
        dry_run: bool = False,
    ) -> ReembedReport:
        """Re-embed every asset whose vectors do not match its chunks.

        Args:
            tenant_id: restrict to one tenant. None scans every tenant.
            dry_run: report what would change without writing anything.
        """
        report = ReembedReport(scanned=self.inspect(tenant_id), dry_run=dry_run)
        todo = [a for a in report.scanned if a.needs_reembedding]

        logger.info(
            "reembed.scanned",
            tenant_id=tenant_id,
            assets=len(report.scanned),
            needs_reembedding=len(todo),
            dry_run=dry_run,
        )

        if dry_run:
            return report

        for asset in todo:
            report.repaired.append(self._reembed(asset))

        logger.info(
            "reembed.done",
            tenant_id=tenant_id,
            repaired=len(report.repaired) - len(report.failures),
            failed=len(report.failures),
            vectors_written=report.vectors_written,
        )
        return report

    def _reembed(self, asset: AssetConsistency) -> ReembedOutcome:
        """Re-embed one asset, converting any failure into a reported outcome.

        One asset failing must not abandon the rest: a reconciliation run over
        a stalled corpus is most useful when it repairs everything it can and
        names what it could not.
        """
        ref = asset.ref
        try:
            result = self._embed.execute(
                asset_id=ref.asset_id,
                tenant_id=ref.tenant_id,
                chunk_strategy=self._strategy_for(asset),
                task_id=_TASK_ID,
                force=True,
            )
            return ReembedOutcome(ref=ref, vectors_written=result.vector_count)

        except Exception as exc:  # noqa: BLE001 — every asset gets its own verdict
            logger.error(
                "reembed.asset_failed",
                asset_id=ref.asset_id,
                tenant_id=ref.tenant_id,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )
            return ReembedOutcome(ref=ref, vectors_written=0, error=str(exc)[:300])

    def _strategy_for(self, asset: AssetConsistency) -> str:
        """Chunk strategy recorded for provenance, read back from the chunks.

        The chunks carry the strategy that produced them, so a reconciliation
        does not have to guess it or force one strategy onto every asset.
        """
        chunks = self._chunks.find_by_asset(asset.ref.asset_id, asset.ref.tenant_id)
        for chunk in chunks:
            strategy = chunk.metadata.get("chunk_strategy")
            if strategy:
                return str(strategy)
        return "UNKNOWN"


__all__ = ["ReembedAssetsUseCase"]
