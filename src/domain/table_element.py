from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TableElement:
    """Normalized representation of a table extracted from a document.

    text — plain-text rendering (always present, used as embedding fallback).
    html — original HTML markup when the source was HTML or Unstructured detected it.
    """
    text: str
    html: str | None = None


__all__ = ["TableElement"]
