"""Domain types for reconciling the chunk store against the vector store.

The two can disagree, and each way they disagree needs a different answer.
Chunks are written by the ingest task; vectors by the embed task. Anything that
stops between them — a worker restart, an embed task that was never dispatched,
a change to how collections are laid out — leaves an asset whose text is stored
and whose meaning is not searchable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AssetEmbedState(str, Enum):
    """How one asset's chunks compare to its vectors."""

    CONSISTENT = "consistent"    # chunk count matches recorded vector count
    MISSING    = "missing"       # chunks exist, no vectors — never embedded
    MISMATCHED = "mismatched"    # both exist, counts differ — partial or stale


@dataclass(frozen=True)
class AssetRef:
    """One asset within one tenant. The key both stores are addressed by."""

    asset_id: str
    tenant_id: str


@dataclass(frozen=True)
class AssetConsistency:
    """What the two stores say about one asset."""

    ref: AssetRef
    chunk_count: int
    vector_count: int
    state: AssetEmbedState

    @property
    def needs_reembedding(self) -> bool:
        """True when re-running the embed would fix it."""
        return self.state in (AssetEmbedState.MISSING, AssetEmbedState.MISMATCHED)


@dataclass(frozen=True)
class ReembedOutcome:
    """The result of re-embedding one asset."""

    ref: AssetRef
    vectors_written: int
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class ReembedReport:
    """What a reconciliation run found and did."""

    scanned: list[AssetConsistency] = field(default_factory=list)
    repaired: list[ReembedOutcome] = field(default_factory=list)
    dry_run: bool = False

    def of_state(self, state: AssetEmbedState) -> list[AssetConsistency]:
        return [a for a in self.scanned if a.state == state]

    @property
    def failures(self) -> list[ReembedOutcome]:
        return [o for o in self.repaired if not o.succeeded]

    @property
    def vectors_written(self) -> int:
        return sum(o.vectors_written for o in self.repaired if o.succeeded)

    @property
    def is_consistent(self) -> bool:
        """True when every repairable asset was in fact repaired."""
        repaired = {o.ref for o in self.repaired if o.succeeded}
        return not any(
            a.needs_reembedding and a.ref not in repaired for a in self.scanned
        )


__all__ = [
    "AssetConsistency",
    "AssetEmbedState",
    "AssetRef",
    "ReembedOutcome",
    "ReembedReport",
]
