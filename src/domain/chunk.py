"""
Domain model for a text chunk produced by the ingestion pipeline.

Pure data — no infrastructure dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """A single text chunk with optional metadata (heading path, source, etc.)."""
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["Chunk"]
