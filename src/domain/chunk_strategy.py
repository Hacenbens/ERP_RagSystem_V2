"""
ChunkStrategy — document chunking strategy enum.

Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 8.3

Selected by chunker_factory.py based on document MIME type or metadata tag.
Each value maps to a concrete chunker class in src/workers/chunkers/.
"""
from __future__ import annotations

from enum import Enum


class ChunkStrategy(str, Enum):
    """Six chunking strategies, each optimised for a document type."""

    RECURSIVE = "RECURSIVE"  # generic fallback          → base_chunker.py
    SENTENCE  = "SENTENCE"   # narrative prose            → base_chunker.py
    TOKEN     = "TOKEN"      # dense technical text       → base_chunker.py
    BPMN      = "BPMN"       # BPMN process diagrams/XML  → bpmn_chunker.py
    TAX       = "TAX"        # Algerian tax circulars (DGI) → tax_circular_chunker.py
    SOP       = "SOP"        # Standard Operating Procedures → sop_chunker.py

    @classmethod
    def _missing_(cls, value: object) -> "ChunkStrategy | None":
        """Resolve a strategy name case-insensitively.

        The upload route defaulted to "sop" while every member is uppercase,
        so ChunkStrategy("sop") raised ValueError inside the Celery worker and
        every upload taking the default retried three times into the
        dead-letter queue. Callers should not have to know the casing.
        """
        if isinstance(value, str):
            return cls.__members__.get(value.upper())
        return None


__all__ = ["ChunkStrategy"]
