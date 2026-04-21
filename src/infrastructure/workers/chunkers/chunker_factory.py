"""
ChunkerFactory — selects the correct BaseChunker for a given ChunkStrategy.

Usage
-----
    factory = ChunkerFactory()
    chunker = factory.get_chunker(ChunkStrategy.SOP)
    chunks  = chunker.chunk(document_text)

The factory is stateless and thread-safe — a single instance can be
shared across the worker process.
"""
from __future__ import annotations

from src.domain.chunk import Chunk
from src.domain.chunk_strategy import ChunkStrategy
from src.observability.structured_logger import get_logger
from src.infrastructure.workers.chunkers.base_chunker import BaseChunker
from src.infrastructure.workers.chunkers.bpmn_chunker import BPMNChunker
from src.infrastructure.workers.chunkers.sop_chunker import SOPChunker
from src.infrastructure.workers.chunkers.tax_circular_chunker import TaxCircularChunker

logger = get_logger(__name__)


class UnknownChunkStrategyError(ValueError):
    """Raised when the requested ChunkStrategy has no registered chunker."""


# Maps every ChunkStrategy value to its concrete implementation class.
# RECURSIVE / SENTENCE / TOKEN all use SOPChunker's recursive fallback
# because they represent generic splitting without domain-specific structure.
_STRATEGY_MAP: dict[ChunkStrategy, type[BaseChunker]] = {
    ChunkStrategy.SOP:       SOPChunker,
    ChunkStrategy.BPMN:      BPMNChunker,
    ChunkStrategy.TAX:       TaxCircularChunker,
    ChunkStrategy.RECURSIVE: SOPChunker,   # generic recursive split
    ChunkStrategy.SENTENCE:  SOPChunker,   # paragraph / sentence split
    ChunkStrategy.TOKEN:     SOPChunker,   # token-density split (same base)
}


class ChunkerFactory:
    """Instantiate and return the appropriate chunker for a given strategy."""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def get_chunker(self, strategy: ChunkStrategy) -> BaseChunker:
        """Return a configured chunker for *strategy*.

        Raises:
            UnknownChunkStrategyError: if *strategy* is not in the registry.
        """
        chunker_cls = _STRATEGY_MAP.get(strategy)
        if chunker_cls is None:
            raise UnknownChunkStrategyError(
                f"No chunker registered for strategy {strategy!r}. "
                f"Valid strategies: {[s.value for s in _STRATEGY_MAP]}"
            )
        logger.debug("chunker_factory.selected", strategy=strategy.value, chunker=chunker_cls.__name__)
        return chunker_cls(chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap)

    def chunk(self, text: str, strategy: ChunkStrategy) -> list[Chunk]:
        """Convenience method: get chunker for *strategy* and chunk *text*."""
        return self.get_chunker(strategy).chunk(text)


__all__ = ["ChunkerFactory", "UnknownChunkStrategyError", "Chunk"]
