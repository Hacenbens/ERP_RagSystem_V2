"""
TaxCircularChunker — Algerian DGI tax circular document chunker.

Splits tax circulars by article boundaries.
Patterns recognised (in priority order):
  1. Arabic article headers  — "Article N :", "Art. N :", "ART N"
  2. Titled sections         — "TITRE N", "CHAPITRE N", "SECTION N"
  3. Paragraph breaks        — double newline
  4. Recursive character fallback

Each article or titled section becomes one chunk.
Oversized articles are further split via the recursive fallback.
"""
from __future__ import annotations

import re

from src.domain.chunk import Chunk
from src.observability.structured_logger import get_logger
from src.infrastructure.workers.chunkers.base_chunker import BaseChunker

logger = get_logger(__name__)

# Article and section boundary patterns (case-insensitive)
_ARTICLE_PATTERN = re.compile(
    r"(?mi)^(?:Article|Art\.)\s+\d+\s*[:\-–]?",
)
_SECTION_PATTERN = re.compile(
    r"(?mi)^(?:TITRE|CHAPITRE|SECTION)\s+(?:\d+|[IVXivx]+)\b",
)

# Combined boundary: match either pattern
_BOUNDARY_PATTERN = re.compile(
    r"(?mi)^(?:(?:Article|Art\.)\s+\d+\s*[:\-–]?|(?:TITRE|CHAPITRE|SECTION)\s+(?:\d+|[IVXivx]+)\b)",
)


class TaxCircularChunker(BaseChunker):
    """Chunk Algerian DGI tax circular documents by article / section."""

    def chunk(self, text: str) -> list[Chunk]:
        """Return one chunk per article or titled section."""
        logger.debug("tax_chunker.start", text_length=len(text))

        if not text.strip():
            return []

        sections = self._split_on_boundaries(text)
        strings: list[str] = []
        for section in sections:
            section = section.strip()
            if not section:
                continue
            if len(section) <= self.chunk_size:
                strings.append(section)
            else:
                strings.extend(self._recursive_split(section))

        result = [Chunk(text=c) for c in strings if c]
        logger.debug("tax_chunker.done", chunk_count=len(result))
        return result

    def _split_on_boundaries(self, text: str) -> list[str]:
        """Split text at every article / section boundary."""
        boundaries = [m.start() for m in _BOUNDARY_PATTERN.finditer(text)]
        if not boundaries:
            # No article markers — fall back to paragraph split
            return [p for p in text.split("\n\n") if p.strip()]

        sections: list[str] = []
        if boundaries[0] > 0:
            preamble = text[: boundaries[0]].strip()
            if preamble:
                sections.append(preamble)
        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
            sections.append(text[start:end])
        return sections


__all__ = ["TaxCircularChunker"]
