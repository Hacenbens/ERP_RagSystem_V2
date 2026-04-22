"""
TaxCircularChunker — Algerian DGI tax circular document chunker.

Document Layout Analysis strategy (Unstructured.io):
  1. Detect input format:
       HTML input  → partition_html yields typed Table elements with text_as_html
       Plain text  → ASCII table blocks isolated by regex before partitioning
  2. Tables and text are processed separately:
       Text   → grouped by article / section boundary, then split via
                RecursiveCharacterTextSplitter when the section exceeds chunk_size
       Tables → compact summary stored in Chunk.text for vector embedding;
                full table (plain text + HTML when available) in Chunk.metadata
                so the complete structure is returned on retrieval match
  3. Fallback: if Unstructured is unavailable or finds no elements, the regex-only
     pipeline (article boundaries + recursive split) is used.

Chunk.metadata keys:
  chunk_type      — "text" | "table_summary"
  section_heading — nearest Title element / TITRE|CHAPITRE heading
  article_heading — "Article N" / "Art. N" marker when the chunk opens one
  element_type    — Unstructured element class name (NarrativeText, Title, …)
  table_raw       — full plain-text content of the table  [table_summary only]
  table_html      — <table> HTML markup when available    [table_summary only]
"""
from __future__ import annotations

from typing import Any

from src.domain.chunk import Chunk
from src.domain.table_element import TableElement
from src.observability.structured_logger import get_logger
from src.infrastructure.workers.chunkers.base_chunker import BaseChunker
from src.infrastructure.workers.chunkers.helpers.table_helpers import (
    PLACEHOLDER_RE,
    build_table_summary,
    extract_ascii_tables,
    is_html,
)
from src.infrastructure.workers.chunkers.helpers.text_helpers import (
    BOUNDARY_PATTERN,
    split_on_boundaries,
)

try:
    from unstructured.partition.html import partition_html
    from unstructured.partition.text import partition_text
    from unstructured.documents.elements import Table as _UnstructuredTable
    _UNSTRUCTURED_AVAILABLE = True
except ImportError:
    _UNSTRUCTURED_AVAILABLE = False

logger = get_logger(__name__)


class TaxCircularChunker(BaseChunker):
    """Chunk Algerian DGI tax circular documents using layout analysis."""

    def chunk(self, text: str) -> list[Chunk]:
        """Return chunks: text split by article boundary + tables as summary+raw."""
        logger.debug("tax_chunker.start", text_length=len(text))

        if not text.strip():
            return []

        if not _UNSTRUCTURED_AVAILABLE:
            logger.warning("tax_chunker.unstructured_unavailable — using regex fallback")
            chunks = self._fallback_regex(text)
        elif is_html(text):
            chunks = self._chunk_html(text)
        else:
            chunks = self._chunk_plaintext(text)

        if not chunks:
            chunks = self._fallback_regex(text)

        logger.debug("tax_chunker.done", chunk_count=len(chunks))
        return chunks

    # ------------------------------------------------------------------
    # HTML path — partition_html yields Table elements with text_as_html
    # ------------------------------------------------------------------

    def _chunk_html(self, text: str) -> list[Chunk]:
        try:
            elements = partition_html(text=text)
        except Exception as exc:
            logger.warning("tax_chunker.partition_html_failed", error=str(exc))
            return []

        ordered: list[tuple[str, Any]] = []
        for elem in elements:
            if isinstance(elem, _UnstructuredTable):
                html_meta = getattr(getattr(elem, "metadata", None), "text_as_html", None)
                ordered.append(("table", TableElement(text=elem.text or "", html=html_meta)))
            else:
                ordered.append(("element", elem))

        return self._process_ordered(ordered)

    # ------------------------------------------------------------------
    # Plain-text path — extract ASCII tables, partition remaining text
    # ------------------------------------------------------------------

    def _chunk_plaintext(self, text: str) -> list[Chunk]:
        sanitized, tables = extract_ascii_tables(text)

        try:
            text_elements = partition_text(text=sanitized)
        except Exception as exc:
            logger.warning("tax_chunker.partition_text_failed", error=str(exc))
            return []

        if not text_elements and not tables:
            return []

        referenced: set[int] = set()
        ordered: list[tuple[str, Any]] = []

        for elem in text_elements:
            m = PLACEHOLDER_RE.fullmatch((elem.text or "").strip())
            if m:
                idx = int(m.group(1))
                referenced.add(idx)
                ordered.append(("table", tables[idx]))
            else:
                ordered.append(("element", elem))

        # Append any table blocks that were not embedded in element text
        for idx, table in enumerate(tables):
            if idx not in referenced:
                ordered.append(("table", table))

        return self._process_ordered(ordered)

    # ------------------------------------------------------------------
    # Shared ordered-element processor
    # ------------------------------------------------------------------

    def _process_ordered(self, ordered: list[tuple[str, Any]]) -> list[Chunk]:
        """Walk (kind, payload) pairs, flushing text blocks at table boundaries."""
        chunks: list[Chunk] = []
        pending: list[str] = []
        section_heading: str = ""

        for kind, payload in ordered:
            if kind == "table":
                chunks.extend(self._flush_text(pending, section_heading))
                pending = []
                chunks.append(self._make_table_chunk(payload, section_heading))
            else:
                elem_text = (payload.text or "").strip()
                if not elem_text:
                    continue
                if type(payload).__name__ == "Title":
                    section_heading = elem_text
                pending.append(elem_text)

        chunks.extend(self._flush_text(pending, section_heading))
        return chunks

    # ------------------------------------------------------------------
    # Table chunk builder
    # ------------------------------------------------------------------

    def _make_table_chunk(self, table: TableElement, section_heading: str) -> Chunk:
        """Summary in Chunk.text for embedding; full table in metadata for retrieval."""
        meta: dict[str, Any] = {
            "chunk_type": "table_summary",
            "section_heading": section_heading,
            "element_type": "Table",
            "table_raw": table.text,
        }
        if table.html:
            meta["table_html"] = table.html

        return Chunk(text=build_table_summary(table), metadata=meta)

    # ------------------------------------------------------------------
    # Text-block helpers
    # ------------------------------------------------------------------

    def _flush_text(self, parts: list[str], section_heading: str) -> list[Chunk]:
        if not parts:
            return []
        return self._chunk_text_block("\n\n".join(parts), section_heading)

    def _chunk_text_block(self, text: str, section_heading: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        for section in split_on_boundaries(text):
            section = section.strip()
            if not section:
                continue
            meta: dict[str, Any] = {
                "chunk_type": "text",
                "section_heading": section_heading,
                "element_type": "text",
            }
            m = BOUNDARY_PATTERN.match(section)
            if m:
                meta["article_heading"] = m.group(0).strip()

            if len(section) <= self.chunk_size:
                chunks.append(Chunk(text=section, metadata=meta))
            else:
                for sub in self._recursive_split(section):
                    if sub:
                        chunks.append(Chunk(text=sub, metadata=meta))
        return chunks

    # ------------------------------------------------------------------
    # Fallback — pure regex, no Unstructured dependency
    # ------------------------------------------------------------------

    def _fallback_regex(self, text: str) -> list[Chunk]:
        return self._chunk_text_block(text, section_heading="")


__all__ = ["TaxCircularChunker"]
