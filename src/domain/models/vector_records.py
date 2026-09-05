"""
Domain types returned by the vector database provider.

Kept free of any driver's shapes: a Milvus hit, a Qdrant point and a pgvector
row all arrive here as the same thing, so swapping providers does not ripple
into the use cases.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorSearchHit:
    """One result from a similarity search.

    ``score`` is the provider's similarity under the collection's metric —
    COSINE here, where higher is more similar. Providers that report a distance
    instead must invert it before constructing this, so callers never have to
    know which convention is in play.
    """

    record_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectionInfo:
    """Structural metadata about a collection.

    ``embedding_size`` is None when the provider cannot report it without an
    extra round trip; absent is stated rather than guessed at.
    """

    name: str
    record_count: int
    embedding_size: int | None = None


__all__ = ["CollectionInfo", "VectorSearchHit"]
