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


__all__ = ["ChunkStrategy"]
