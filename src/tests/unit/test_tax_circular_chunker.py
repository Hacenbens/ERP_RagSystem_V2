"""
Unit tests — Sprint 6 Task 3
Covers: TaxCircularChunker, table_helpers, text_helpers, TableElement domain model

Test strategy
-------------
- All tests are pure in-memory — no network, no filesystem I/O.
- Unstructured.io is exercised directly (installed in the venv).
- The regex-fallback path is tested by patching _UNSTRUCTURED_AVAILABLE to False.
- Helpers are tested independently of the chunker.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.domain.chunk import Chunk
from src.domain.table_element import TableElement
from src.infrastructure.workers.chunkers.tax_circular_chunker import TaxCircularChunker
from src.infrastructure.workers.chunkers.helpers.table_helpers import (
    build_table_summary,
    extract_ascii_tables,
    is_html,
)
from src.infrastructure.workers.chunkers.helpers.text_helpers import (
    BOUNDARY_PATTERN,
    split_on_boundaries,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ARTICLE_TEXT = """\
TITRE I — DISPOSITIONS GENERALES

Article 1 : Champ d'application
Les dispositions de la présente circulaire s'appliquent à toutes les entreprises
soumises à l'impôt sur les bénéfices des sociétés (IBS).

Article 2 : Obligations déclaratives
Les contribuables sont tenus de déposer leur déclaration annuelle avant le 30 avril.
"""

ASCII_TABLE = """\
| Tranche de revenu       | Taux IBS |
|-------------------------|----------|
| 0 - 1 000 000 DA        | 19 %     |
| 1 000 001 - 5 000 000   | 23 %     |
| Plus de 5 000 000 DA    | 26 %     |
"""

HTML_CIRCULAR = """\
<html><body>
<h1>TITRE I — DISPOSITIONS GENERALES</h1>
<p>Article 1 : Champ d'application. Les dispositions s'appliquent aux entreprises.</p>
<table>
<tr><th>Tranche</th><th>Taux IBS</th></tr>
<tr><td>0 - 1 000 000 DA</td><td>19%</td></tr>
<tr><td>1 000 001 - 5 000 000 DA</td><td>23%</td></tr>
</table>
<p>Article 2 : Obligations. Les contribuables déposent avant le 30 avril.</p>
</body></html>"""

PLAIN_WITH_TABLE = """\
TITRE II — TAUX D'IMPOSITION

Article 3 : Barème

| Type              | Taux  | Plafond     |
|-------------------|-------|-------------|
| Déclaration tardive | 10% | 100 000 DA  |
| Fraude avérée     | 100%  | Aucun       |

Article 4 : Recours
Tout contribuable peut introduire un recours dans les 30 jours suivant la notification.
"""


# ===========================================================================
# TableElement domain model
# ===========================================================================

class TestTableElement:
    def test_stores_text(self):
        elem = TableElement(text="col A | col B")
        assert elem.text == "col A | col B"

    def test_html_defaults_to_none(self):
        elem = TableElement(text="x")
        assert elem.html is None

    def test_stores_html_when_provided(self):
        elem = TableElement(text="x", html="<table></table>")
        assert elem.html == "<table></table>"


# ===========================================================================
# table_helpers
# ===========================================================================

class TestIsHtml:
    def test_returns_true_for_html_tag(self):
        assert is_html("<html><body>hello</body></html>") is True

    def test_returns_true_for_body_tag(self):
        assert is_html("<body>content</body>") is True

    def test_returns_true_for_table_tag(self):
        assert is_html("<table><tr><td>x</td></tr></table>") is True

    def test_returns_true_for_div_tag(self):
        assert is_html("<div>content</div>") is True

    def test_returns_false_for_plain_text(self):
        assert is_html("Article 1 : Champ d'application.") is False

    def test_returns_false_for_empty_string(self):
        assert is_html("") is False

    def test_returns_false_for_whitespace(self):
        assert is_html("   \n   ") is False

    def test_detection_is_case_insensitive(self):
        assert is_html("<HTML><BODY>test</BODY></HTML>") is True


class TestBuildTableSummary:
    def test_starts_with_table_prefix(self):
        elem = TableElement(text="| Col A | Col B |\n| val1  | val2  |\n")
        assert build_table_summary(elem).startswith("[Table]")

    def test_includes_row_count(self):
        elem = TableElement(text="| Col A | Col B |\n|-------|-------|\n| v1 | v2 |\n| v3 | v4 |\n")
        summary = build_table_summary(elem)
        assert "2 rows" in summary

    def test_singular_row_label(self):
        elem = TableElement(text="| Col A |\n|-------|\n| val1  |\n")
        assert "1 row" in build_table_summary(elem)
        assert "rows" not in build_table_summary(elem)

    def test_empty_element_returns_empty_marker(self):
        assert build_table_summary(TableElement(text="")) == "[Table] (empty)"
        assert build_table_summary(TableElement(text="   ")) == "[Table] (empty)"

    def test_separator_lines_not_counted_as_data_rows(self):
        elem = TableElement(text="| Header |\n|--------|\n| data   |\n")
        summary = build_table_summary(elem)
        assert "1 row" in summary

    def test_header_truncated_at_120_chars(self):
        long_header = "| " + "x" * 200 + " |"
        elem = TableElement(text=long_header + "\n| data |\n")
        summary = build_table_summary(elem)
        assert len(summary) < 200

    def test_pipe_decorators_cleaned_from_header(self):
        elem = TableElement(text="| Tranche | Taux |\n| 0-1M | 19% |\n")
        summary = build_table_summary(elem)
        assert summary.startswith("[Table] Tranche")


class TestExtractAsciiTables:
    def test_extracts_pipe_table_block(self):
        _, tables = extract_ascii_tables(ASCII_TABLE)
        assert len(tables) == 1

    def test_extracted_table_raw_contains_original_content(self):
        _, tables = extract_ascii_tables(ASCII_TABLE)
        assert "Tranche de revenu" in tables[0].text

    def test_sanitized_text_has_no_pipe_lines(self):
        sanitized, _ = extract_ascii_tables(ASCII_TABLE)
        assert "|" not in sanitized

    def test_plain_text_without_tables_unchanged(self):
        plain = "Article 1 : No tables here.\n\nArticle 2 : Still no tables.\n"
        sanitized, tables = extract_ascii_tables(plain)
        assert tables == []
        assert sanitized == plain

    def test_multiple_tables_extracted_in_order(self):
        two_tables = (
            "Intro text.\n"
            + ASCII_TABLE
            + "Middle text.\n"
            + ASCII_TABLE
            + "Outro text.\n"
        )
        _, tables = extract_ascii_tables(two_tables)
        assert len(tables) == 2

    def test_table_html_is_none_for_plain_text(self):
        _, tables = extract_ascii_tables(ASCII_TABLE)
        assert tables[0].html is None

    def test_single_pipe_line_not_extracted(self):
        # A single pipe line should NOT be treated as a table (needs 2+)
        single = "| just one line |\nNot a table.\n"
        _, tables = extract_ascii_tables(single)
        assert len(tables) == 0


# ===========================================================================
# text_helpers
# ===========================================================================

class TestSplitOnBoundaries:
    def test_splits_on_article(self):
        text = "Preamble.\n\nArticle 1 : First.\n\nArticle 2 : Second.\n"
        sections = split_on_boundaries(text)
        assert any("Article 1" in s for s in sections)
        assert any("Article 2" in s for s in sections)

    def test_splits_on_art_dot(self):
        text = "Art. 1 : Premier article.\n\nArt. 2 : Deuxième article.\n"
        sections = split_on_boundaries(text)
        assert len(sections) == 2

    def test_splits_on_titre(self):
        text = "TITRE I — Premier.\n\nTITRE II — Deuxième.\n"
        sections = split_on_boundaries(text)
        assert len(sections) == 2

    def test_splits_on_chapitre(self):
        text = "CHAPITRE 1 — Intro.\n\nCHAPITRE 2 — Suite.\n"
        sections = split_on_boundaries(text)
        assert len(sections) == 2

    def test_splits_on_section(self):
        text = "SECTION I — Généralités.\n\nSECTION II — Détails.\n"
        sections = split_on_boundaries(text)
        assert len(sections) == 2

    def test_preamble_before_first_article_is_included(self):
        text = "Introduction.\n\nArticle 1 : Corps.\n"
        sections = split_on_boundaries(text)
        assert sections[0].startswith("Introduction")

    def test_fallback_to_paragraph_split_when_no_markers(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three.\n"
        sections = split_on_boundaries(text)
        assert len(sections) == 3

    def test_empty_input_returns_empty_list(self):
        assert split_on_boundaries("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert split_on_boundaries("   \n\n   ") == []

    def test_roman_numeral_section_recognised(self):
        text = "TITRE IV — Titre quatre.\n\nTITRE IX — Titre neuf.\n"
        sections = split_on_boundaries(text)
        assert len(sections) == 2


class TestBoundaryPattern:
    @pytest.mark.parametrize("header", [
        "Article 1 :",
        "Article 12 -",
        "Art. 3 :",
        "TITRE I",
        "TITRE 2",
        "CHAPITRE III",
        "SECTION iv",
    ])
    def test_pattern_matches_valid_headers(self, header: str):
        assert BOUNDARY_PATTERN.search(header) is not None

    @pytest.mark.parametrize("non_header", [
        "This is not an article",
        "article without capital",
        "titre without spaces",
    ])
    def test_pattern_does_not_match_plain_text(self, non_header: str):
        assert BOUNDARY_PATTERN.search(non_header) is None


# ===========================================================================
# TaxCircularChunker — edge cases and base constraints
# ===========================================================================

class TestTaxCircularChunkerEdgeCases:
    def test_empty_input_returns_empty_list(self):
        assert TaxCircularChunker().chunk("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert TaxCircularChunker().chunk("   \n\n  ") == []

    def test_invalid_overlap_raises(self):
        with pytest.raises(ValueError, match="chunk_overlap"):
            TaxCircularChunker(chunk_size=100, chunk_overlap=100)

    def test_all_chunks_are_nonempty(self):
        chunker = TaxCircularChunker()
        for chunk in chunker.chunk(ARTICLE_TEXT):
            assert chunk.text.strip() != ""

    def test_all_chunks_are_chunk_instances(self):
        chunker = TaxCircularChunker()
        for chunk in chunker.chunk(ARTICLE_TEXT):
            assert isinstance(chunk, Chunk)

    def test_oversized_section_produces_multiple_chunks(self):
        long_article = "Article 1 : " + ("word " * 500)
        chunker = TaxCircularChunker(chunk_size=200, chunk_overlap=20)
        chunks = chunker.chunk(long_article)
        assert len(chunks) > 1


# ===========================================================================
# TaxCircularChunker — fallback regex path
# ===========================================================================

class TestTaxCircularChunkerFallbackRegex:
    """Exercises _fallback_regex by disabling Unstructured at module level."""

    @pytest.fixture(autouse=True)
    def disable_unstructured(self):
        with patch(
            "src.infrastructure.workers.chunkers.tax_circular_chunker._UNSTRUCTURED_AVAILABLE",
            False,
        ):
            yield

    def test_article_boundaries_produce_separate_chunks(self):
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(ARTICLE_TEXT)
        texts = [c.text for c in chunks]
        assert any("Article 1" in t for t in texts)
        assert any("Article 2" in t for t in texts)

    def test_titre_boundary_produces_its_own_chunk(self):
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(ARTICLE_TEXT)
        assert any("TITRE I" in c.text for c in chunks)

    def test_preamble_before_first_marker_included(self):
        text = "Préambule introductif.\n\nArticle 1 : Corps.\n"
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(text)
        assert any("Préambule" in c.text for c in chunks)

    def test_no_markers_paragraph_fallback(self):
        text = "Premier paragraphe.\n\nDeuxième paragraphe.\n\nTroisième paragraphe.\n"
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(text)
        assert len(chunks) == 3

    def test_all_chunk_types_are_text(self):
        chunker = TaxCircularChunker()
        for chunk in chunker.chunk(ARTICLE_TEXT):
            assert chunk.metadata["chunk_type"] == "text"

    def test_chunk_metadata_has_element_type(self):
        chunker = TaxCircularChunker()
        for chunk in chunker.chunk(ARTICLE_TEXT):
            assert "element_type" in chunk.metadata


# ===========================================================================
# TaxCircularChunker — HTML path
# ===========================================================================

class TestTaxCircularChunkerHtmlPath:
    def test_html_input_yields_chunks(self):
        chunks = TaxCircularChunker().chunk(HTML_CIRCULAR)
        assert len(chunks) > 0

    def test_html_table_produces_table_summary_chunk(self):
        chunks = TaxCircularChunker().chunk(HTML_CIRCULAR)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        assert len(table_chunks) >= 1

    def test_html_table_chunk_text_starts_with_table_prefix(self):
        chunks = TaxCircularChunker().chunk(HTML_CIRCULAR)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        assert all(c.text.startswith("[Table]") for c in table_chunks)

    def test_html_table_chunk_metadata_has_table_raw(self):
        chunks = TaxCircularChunker().chunk(HTML_CIRCULAR)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        for tc in table_chunks:
            assert "table_raw" in tc.metadata
            assert tc.metadata["table_raw"].strip() != ""

    def test_html_table_chunk_metadata_has_table_html(self):
        chunks = TaxCircularChunker().chunk(HTML_CIRCULAR)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        for tc in table_chunks:
            assert "table_html" in tc.metadata
            assert "<table" in tc.metadata["table_html"].lower()

    def test_html_text_chunks_present(self):
        chunks = TaxCircularChunker().chunk(HTML_CIRCULAR)
        text_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "text"]
        assert len(text_chunks) >= 1

    def test_html_table_raw_contains_original_cell_data(self):
        chunks = TaxCircularChunker().chunk(HTML_CIRCULAR)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        assert any("19%" in tc.metadata["table_raw"] for tc in table_chunks)

    def test_html_table_chunk_element_type_is_table(self):
        chunks = TaxCircularChunker().chunk(HTML_CIRCULAR)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        for tc in table_chunks:
            assert tc.metadata["element_type"] == "Table"


# ===========================================================================
# TaxCircularChunker — plain text with ASCII table path
# ===========================================================================

class TestTaxCircularChunkerPlainTextPath:
    def test_ascii_table_produces_table_summary_chunk(self):
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(PLAIN_WITH_TABLE)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        assert len(table_chunks) >= 1

    def test_ascii_table_chunk_text_starts_with_table_prefix(self):
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(PLAIN_WITH_TABLE)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        assert all(c.text.startswith("[Table]") for c in table_chunks)

    def test_ascii_table_raw_stored_in_metadata(self):
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(PLAIN_WITH_TABLE)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        for tc in table_chunks:
            assert tc.metadata["table_raw"].strip() != ""
            assert "|" in tc.metadata["table_raw"]

    def test_ascii_table_has_no_html_metadata(self):
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(PLAIN_WITH_TABLE)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        for tc in table_chunks:
            assert "table_html" not in tc.metadata

    def test_text_around_table_also_chunked(self):
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(PLAIN_WITH_TABLE)
        text_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "text"]
        assert len(text_chunks) >= 1

    def test_article_heading_set_in_metadata(self):
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(PLAIN_WITH_TABLE)
        text_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "text"]
        article_chunks = [c for c in text_chunks if "article_heading" in c.metadata]
        assert len(article_chunks) >= 1

    def test_multiple_ascii_tables_all_produce_table_chunks(self):
        two_tables = (
            "Article 1 : Premier barème.\n"
            + ASCII_TABLE
            + "Article 2 : Deuxième barème.\n"
            + ASCII_TABLE
        )
        chunker = TaxCircularChunker()
        chunks = chunker.chunk(two_tables)
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table_summary"]
        assert len(table_chunks) == 2


# ===========================================================================
# TaxCircularChunker — chunk metadata contract
# ===========================================================================

class TestChunkMetadataContract:
    """Every chunk must carry the documented metadata keys regardless of path."""

    def test_text_chunk_has_chunk_type_key(self):
        chunker = TaxCircularChunker()
        for chunk in chunker.chunk(ARTICLE_TEXT):
            assert "chunk_type" in chunk.metadata

    def test_text_chunk_has_section_heading_key(self):
        chunker = TaxCircularChunker()
        for chunk in chunker.chunk(ARTICLE_TEXT):
            assert "section_heading" in chunk.metadata

    def test_text_chunk_has_element_type_key(self):
        chunker = TaxCircularChunker()
        for chunk in chunker.chunk(ARTICLE_TEXT):
            assert "element_type" in chunk.metadata

    def test_table_summary_chunk_has_table_raw_key(self):
        chunks = TaxCircularChunker().chunk(PLAIN_WITH_TABLE)
        for chunk in chunks:
            if chunk.metadata["chunk_type"] == "table_summary":
                assert "table_raw" in chunk.metadata

    def test_table_summary_chunk_summary_is_not_full_raw(self):
        """The summary in .text must be shorter than the raw table."""
        chunks = TaxCircularChunker().chunk(PLAIN_WITH_TABLE)
        for chunk in chunks:
            if chunk.metadata["chunk_type"] == "table_summary":
                assert len(chunk.text) < len(chunk.metadata["table_raw"])

    def test_article_heading_only_on_article_starting_chunks(self):
        """article_heading must only appear when the section starts with an article marker."""
        chunker = TaxCircularChunker()
        for chunk in chunker.chunk(ARTICLE_TEXT):
            if "article_heading" in chunk.metadata:
                heading = chunk.metadata["article_heading"]
                assert BOUNDARY_PATTERN.match(heading) is not None
