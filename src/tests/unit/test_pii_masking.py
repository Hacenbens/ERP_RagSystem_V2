"""
Unit tests — PIIMaskingMiddleware._mask_pii() (Sprint 5, Tasks 3 & 4).

Acceptance criteria:
  - Overall recall >= 98% across 30 fixture queries
  - Each PII type (email, phone_dz, nid_dz, tax_id_dz) individually >= 95% recall
  - True-negative queries produce zero masked entities (no false positives)
  - Masked output contains [REDACTED:<TYPE>] token for every detected entity
  - Edge cases (phone with spaces, 14-digit, 19-digit) are NOT masked

Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 8
Naming: test_{function}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.middleware.PIIMaskingMiddleware import _mask_pii

# ---------------------------------------------------------------------------
# Load fixture
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "pii_test_queries.json"
_QUERIES: list[dict[str, Any]] = json.loads(_FIXTURE_PATH.read_text())

_ENTITY_TYPES = ("email", "phone_dz", "nid_dz", "tax_id_dz")

# Recall threshold constants (acceptance criteria)
_OVERALL_RECALL_THRESHOLD = 0.98
_PER_TYPE_RECALL_THRESHOLD = 0.95


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(query: dict[str, Any]) -> tuple[str, dict[str, int]]:
    """Run _mask_pii on query text; return (masked_text, counts)."""
    return _mask_pii(query["text"])


def _redacted_token(entity_type: str) -> str:
    return f"[REDACTED:{entity_type.upper()}]"


# ---------------------------------------------------------------------------
# Per-query correctness tests
# ---------------------------------------------------------------------------

class TestEmailMasking:
    """Email addresses are detected and replaced."""

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["email"] > 0])
    def test_email_detected_in_query(self, query):
        masked, counts = _run(query)
        assert counts.get("email", 0) == query["expected"]["email"], (
            f"Query {query['id']}: expected {query['expected']['email']} email(s), "
            f"got {counts.get('email', 0)}"
        )

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["email"] > 0])
    def test_redacted_token_present_for_email(self, query):
        masked, _ = _run(query)
        assert _redacted_token("email") in masked, (
            f"Query {query['id']}: [REDACTED:EMAIL] not found in output"
        )

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["email"] > 0])
    def test_raw_email_not_in_masked_output(self, query):
        masked, _ = _run(query)
        assert "@" not in masked or _redacted_token("email") in masked, (
            f"Query {query['id']}: raw email address may still be present"
        )


class TestPhoneDzMasking:
    """Algerian mobile numbers (+213 and 0[5-7] prefixes) are detected."""

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["phone_dz"] > 0])
    def test_phone_dz_detected_in_query(self, query):
        masked, counts = _run(query)
        assert counts.get("phone_dz", 0) == query["expected"]["phone_dz"], (
            f"Query {query['id']}: expected {query['expected']['phone_dz']} phone(s), "
            f"got {counts.get('phone_dz', 0)}"
        )

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["phone_dz"] > 0])
    def test_redacted_token_present_for_phone(self, query):
        masked, _ = _run(query)
        assert _redacted_token("phone_dz") in masked


class TestNidDzMasking:
    """18-digit Algerian national IDs are detected with word-boundary anchors."""

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["nid_dz"] > 0])
    def test_nid_dz_detected_in_query(self, query):
        masked, counts = _run(query)
        assert counts.get("nid_dz", 0) == query["expected"]["nid_dz"], (
            f"Query {query['id']}: expected {query['expected']['nid_dz']} NID(s), "
            f"got {counts.get('nid_dz', 0)}"
        )

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["nid_dz"] > 0])
    def test_redacted_token_present_for_nid(self, query):
        masked, _ = _run(query)
        assert _redacted_token("nid_dz") in masked


class TestTaxIdDzMasking:
    """15-digit Algerian tax IDs (NIF) are detected with word-boundary anchors."""

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["tax_id_dz"] > 0])
    def test_tax_id_dz_detected_in_query(self, query):
        masked, counts = _run(query)
        assert counts.get("tax_id_dz", 0) == query["expected"]["tax_id_dz"], (
            f"Query {query['id']}: expected {query['expected']['tax_id_dz']} tax ID(s), "
            f"got {counts.get('tax_id_dz', 0)}"
        )

    @pytest.mark.parametrize("query", [q for q in _QUERIES if q["expected"]["tax_id_dz"] > 0])
    def test_redacted_token_present_for_tax_id(self, query):
        masked, _ = _run(query)
        assert _redacted_token("tax_id_dz") in masked


# ---------------------------------------------------------------------------
# True-negative tests — no PII must produce zero detections
# ---------------------------------------------------------------------------

class TestTrueNegatives:
    """Queries with no PII must produce empty counts (zero false positives)."""

    _NO_PII = [q for q in _QUERIES if all(v == 0 for v in q["expected"].values())]

    @pytest.mark.parametrize("query", _NO_PII)
    def test_clean_query_produces_no_detections(self, query):
        _, counts = _run(query)
        assert counts == {}, (
            f"Query {query['id']} ({query['description']}): "
            f"unexpected PII detected: {counts}"
        )

    @pytest.mark.parametrize("query", _NO_PII)
    def test_clean_query_text_unchanged(self, query):
        masked, _ = _run(query)
        assert masked == query["text"], (
            f"Query {query['id']}: text was modified despite containing no PII"
        )


# ---------------------------------------------------------------------------
# Edge-case tests — boundary conditions
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary conditions that must NOT trigger false positives."""

    def test_phone_with_spaces_not_detected(self):
        """Pattern requires contiguous digits — spaced phone must be ignored."""
        _, counts = _mask_pii("Contact warehouse at 05 51 23 45 67 for access")
        assert counts.get("phone_dz", 0) == 0

    def test_fourteen_digit_number_not_matched_as_tax_id(self):
        """14-digit run is too short for tax_id_dz (needs exactly 15)."""
        _, counts = _mask_pii("Invoice ref 12345678901234 raised this month")
        assert counts.get("tax_id_dz", 0) == 0

    def test_nineteen_digit_number_not_matched_as_nid(self):
        """19-digit run is too long for nid_dz (needs exactly 18)."""
        _, counts = _mask_pii("Batch ID 1234567890123456789 processed successfully")
        assert counts.get("nid_dz", 0) == 0

    def test_eighteen_digit_nid_not_double_matched_as_tax_id(self):
        """18-digit NID is masked first; tax_id pattern must not re-match it."""
        text = "Employee NID 199001011234567890 is on file"
        masked, counts = _mask_pii(text)
        assert counts.get("nid_dz", 0) == 1
        assert counts.get("tax_id_dz", 0) == 0
        assert _redacted_token("nid_dz") in masked

    def test_empty_string_returns_empty_counts(self):
        masked, counts = _mask_pii("")
        assert masked == ""
        assert counts == {}

    def test_plain_text_no_digits_returns_unchanged(self):
        text = "List all pending orders by region"
        masked, counts = _mask_pii(text)
        assert masked == text
        assert counts == {}

    def test_international_phone_plus213_detected(self):
        """Ensure +213 prefix variant is handled correctly."""
        _, counts = _mask_pii("Call +213551234567 for ERP support")
        assert counts.get("phone_dz", 0) == 1

    def test_phone_prefix_04_not_detected(self):
        """04x prefix is not a valid Algerian mobile prefix."""
        _, counts = _mask_pii("Old landline 0412345678 is decommissioned")
        assert counts.get("phone_dz", 0) == 0


# ---------------------------------------------------------------------------
# Recall accuracy — global and per-type (acceptance criteria)
# ---------------------------------------------------------------------------

class TestRecallAccuracy:
    """Overall recall must be >= 98%; per-type recall >= 95%."""

    @pytest.fixture(scope="class")
    def results(self):
        """Run all queries once and return aggregated TP / expected counts."""
        tp: dict[str, int] = {t: 0 for t in _ENTITY_TYPES}
        expected_total: dict[str, int] = {t: 0 for t in _ENTITY_TYPES}

        for query in _QUERIES:
            _, counts = _mask_pii(query["text"])
            for etype in _ENTITY_TYPES:
                exp = query["expected"][etype]
                det = counts.get(etype, 0)
                expected_total[etype] += exp
                tp[etype] += min(det, exp)  # cap TP at expected (avoid counting FP as TP)

        return {"tp": tp, "expected": expected_total}

    def test_overall_recall_meets_threshold(self, results):
        total_expected = sum(results["expected"].values())
        total_tp = sum(results["tp"].values())
        recall = total_tp / total_expected if total_expected > 0 else 1.0
        assert recall >= _OVERALL_RECALL_THRESHOLD, (
            f"Overall recall {recall:.1%} is below the {_OVERALL_RECALL_THRESHOLD:.0%} threshold "
            f"(TP={total_tp}, expected={total_expected})"
        )

    @pytest.mark.parametrize("entity_type", _ENTITY_TYPES)
    def test_per_type_recall_meets_threshold(self, results, entity_type):
        exp = results["expected"][entity_type]
        if exp == 0:
            pytest.skip(f"No '{entity_type}' instances in fixture — skip per-type check")
        tp = results["tp"][entity_type]
        recall = tp / exp
        assert recall >= _PER_TYPE_RECALL_THRESHOLD, (
            f"{entity_type} recall {recall:.1%} is below the {_PER_TYPE_RECALL_THRESHOLD:.0%} "
            f"threshold (TP={tp}, expected={exp})"
        )

    def test_fixture_has_minimum_query_count(self):
        """Fixture must contain at least 30 queries for statistical validity."""
        assert len(_QUERIES) >= 30, (
            f"Fixture has only {len(_QUERIES)} queries — need at least 30"
        )

    def test_fixture_covers_all_entity_types(self):
        """Every PII entity type must appear at least once in the fixture."""
        for etype in _ENTITY_TYPES:
            total = sum(q["expected"][etype] for q in _QUERIES)
            assert total > 0, f"Entity type '{etype}' has no instances in fixture"

    def test_fixture_has_true_negative_queries(self):
        """At least 20% of queries must be PII-free (tests false-positive resistance)."""
        no_pii = [q for q in _QUERIES if all(v == 0 for v in q["expected"].values())]
        ratio = len(no_pii) / len(_QUERIES)
        assert ratio >= 0.20, (
            f"Only {len(no_pii)}/{len(_QUERIES)} ({ratio:.0%}) queries are PII-free; "
            "need at least 20%"
        )
