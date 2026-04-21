from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Article / section boundary pattern for Algerian DGI tax circulars
# Matches (case-insensitive, at start of line):
#   Article N [: | - | –]   or   Art. N [: | - | –]
#   TITRE N | CHAPITRE N | SECTION N   (decimal or roman numeral)
# ---------------------------------------------------------------------------

BOUNDARY_PATTERN = re.compile(
    r"(?mi)^(?:"
    r"(?:Article|Art\.)\s+\d+\s*[:\-–]?"
    r"|(?:TITRE|CHAPITRE|SECTION)\s+(?:\d+|[IVXivx]+)\b"
    r")",
)


def split_on_boundaries(text: str) -> list[str]:
    """Split *text* at every article / section boundary.

    If no boundary markers are found, falls back to paragraph splitting
    on double newlines.
    """
    boundaries = [m.start() for m in BOUNDARY_PATTERN.finditer(text)]
    if not boundaries:
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


__all__ = ["BOUNDARY_PATTERN", "split_on_boundaries"]
