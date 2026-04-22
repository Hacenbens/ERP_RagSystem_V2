from __future__ import annotations

import re

from src.domain.table_element import TableElement

# ---------------------------------------------------------------------------
# Regex: ASCII pipe-formatted table block (2+ consecutive pipe lines)
# ---------------------------------------------------------------------------

ASCII_TABLE_RE = re.compile(r"(?m)(?:^[ \t]*\|[^\n]*\n){2,}")

# Null-byte delimited placeholder — survives text partitioning without confusion
TABLE_PLACEHOLDER = "\x00TABLE_{index}\x00"
PLACEHOLDER_RE = re.compile(r"\x00TABLE_(\d+)\x00")


def is_html(text: str) -> bool:
    """Return True when text begins with HTML markup."""
    probe = text.strip()[:300].lower()
    return any(tag in probe for tag in ("<html", "<body", "<table", "<div"))


def build_table_summary(element: TableElement) -> str:
    """Return a compact, embedding-friendly one-liner describing a table.

    Format: '[Table] <header row> — N data rows'
    The full table lives in TableElement.text / .html and is carried in
    Chunk.metadata for retrieval — this summary is only for vector search.
    """
    lines = [ln.strip() for ln in element.text.splitlines() if ln.strip()]
    if not lines:
        return "[Table] (empty)"

    # First non-separator line is the header
    header = next(
        (ln for ln in lines if not re.fullmatch(r"[\|\-\+\s=]+", ln)),
        lines[0],
    )
    header = re.sub(r"\s*\|\s*", " | ", header).strip("| ").strip()

    data_rows = sum(
        1 for ln in lines[1:]
        if ln and not re.fullmatch(r"[\|\-\+\s=]+", ln)
    )
    label = "row" if data_rows == 1 else "rows"
    return f"[Table] {header[:120]} — {data_rows} {label}"


def extract_ascii_tables(text: str) -> tuple[str, list[TableElement]]:
    """Replace ASCII table blocks in *text* with numbered placeholders.

    Returns:
        sanitized  — text with table blocks replaced by ``\\x00TABLE_N\\x00``
        tables     — ordered list of TableElement for each extracted block
    """
    tables: list[TableElement] = []

    def _replace(m: re.Match) -> str:
        idx = len(tables)
        tables.append(TableElement(text=m.group(0).strip()))
        return TABLE_PLACEHOLDER.format(index=idx) + "\n"

    sanitized = ASCII_TABLE_RE.sub(_replace, text)
    return sanitized, tables


__all__ = [
    "ASCII_TABLE_RE",
    "TABLE_PLACEHOLDER",
    "PLACEHOLDER_RE",
    "is_html",
    "build_table_summary",
    "extract_ascii_tables",
]
