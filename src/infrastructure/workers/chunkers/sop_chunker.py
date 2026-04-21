"""
SOPChunker — Standard Operating Procedure / Handbook / Policy document chunker.

Strategy:
  1. MarkdownHeaderTextSplitter (LangChain) — groups content under its heading.
     Headers tracked: #, ##, ###, ####
  2. If a section exceeds chunk_size, RecursiveCharacterTextSplitter further
     splits it — every sub-chunk inherits the parent heading in its metadata.
  3. If no Markdown headers are found, RecursiveCharacterTextSplitter is used
     directly on the full text.

Every returned Chunk carries metadata keys:
  - h1 / h2 / h3 / h4  — heading values at each level (when present)
  - parent_heading       — breadcrumb string, e.g. "Intro > Overview"
"""
from __future__ import annotations

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.domain.chunk import Chunk
from src.observability.structured_logger import get_logger
from src.infrastructure.workers.chunkers.base_chunker import BaseChunker

logger = get_logger(__name__)

_HEADERS_TO_SPLIT = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
    ("####", "h4"),
]


def _build_parent_heading(metadata: dict) -> str:
    """Build a breadcrumb string from LangChain header metadata."""
    parts = [metadata[k] for k in ("h1", "h2", "h3", "h4") if metadata.get(k)]
    return " > ".join(parts)


class SOPChunker(BaseChunker):
    """Chunk SOP / Handbook / Policy documents using header-based splitting."""

    def chunk(self, text: str) -> list[Chunk]:
        logger.debug("sop_chunker.start", text_length=len(text))

        if not text.strip():
            return []

        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=_HEADERS_TO_SPLIT,
            strip_headers=False,
        )
        rc_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        docs = md_splitter.split_text(text)

        # No Markdown headers found — fall back to recursive split with no metadata
        if not docs or (len(docs) == 1 and not docs[0].metadata):
            plain_chunks = rc_splitter.split_text(text)
            result = [Chunk(text=c.strip()) for c in plain_chunks if c.strip()]
            logger.debug("sop_chunker.done_fallback", chunk_count=len(result))
            return result

        chunks: list[Chunk] = []
        for doc in docs:
            content = doc.page_content.strip()
            if not content:
                continue

            meta = {**doc.metadata, "parent_heading": _build_parent_heading(doc.metadata)}

            if len(content) <= self.chunk_size:
                chunks.append(Chunk(text=content, metadata=meta))
            else:
                # Section too long — sub-split and propagate parent heading to every piece
                for sub in rc_splitter.split_text(content):
                    sub = sub.strip()
                    if sub:
                        chunks.append(Chunk(text=sub, metadata=meta))

        logger.debug("sop_chunker.done", chunk_count=len(chunks))
        return chunks


__all__ = ["SOPChunker"]
