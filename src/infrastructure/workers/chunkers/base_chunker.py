"""
BaseChunker — abstract base class for all domain-aware chunkers.

Every concrete chunker receives plain text and returns a list of Chunk
objects (text + metadata). The _recursive_split helper delegates to
LangChain's RecursiveCharacterTextSplitter and returns plain strings
so subclasses can wrap them in Chunk with whatever metadata they need.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.domain.chunk import Chunk
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50


class BaseChunker(ABC):
    """Abstract base for all document chunkers."""

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @abstractmethod
    def chunk(self, text: str) -> list[Chunk]:
        """Split *text* into a list of non-empty Chunk objects."""

    # ------------------------------------------------------------------
    # Shared helper — returns plain strings; subclasses wrap into Chunk
    # ------------------------------------------------------------------

    def _recursive_split(self, text: str, separators: list[str] | None = None) -> list[str]:
        """Split *text* via LangChain's RecursiveCharacterTextSplitter.

        Overlap and hard-cut fallback are handled natively by LangChain.
        """
        if not text.strip():
            return []
        kwargs: dict = {}
        if separators is not None:
            kwargs["separators"] = separators
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            **kwargs,
        )
        return [c for c in splitter.split_text(text) if c.strip()]


__all__ = ["BaseChunker", "DEFAULT_CHUNK_SIZE", "DEFAULT_CHUNK_OVERLAP"]
