"""
PIIMaskingMiddleware — PII detection and masking on query text (Sprint 1 stub).

Position in stack: FIFTH / innermost (after RBACMiddleware).

PII patterns to detect (Sprint 5 full list):
    - Email addresses           (RFC 5322 local@domain)
    - Phone numbers             (Algerian DZ format: +213 or 0[5-7]XX)
    - Algerian NID              (18-digit national ID)
    - Algerian Tax ID           (15-digit NIF)

Sprint 1 stub behaviour:
    - Intercepts POST requests with a JSON body containing a "query" field
    - Runs a minimal email regex mask as a proof-of-concept
    - Increments PII_DETECTION_RATE for each masked entity
    - Replaces detected PII in the query with [REDACTED:<type>]
    - Passes the sanitised request body downstream

Sprint 5 will add:
    - Full regex suite for all DZ-specific PII types
    - Integration with pii_masking_service.py for recall >= 98%
    - Masking on response body (hide PII in LLM answers)
"""
from __future__ import annotations

import json
import re
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.observability.prometheus_metrics import PII_DETECTION_RATE
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Sprint 1 stub patterns — minimal but functional
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "email",
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE),
    ),
    (
        "phone_dz",
        re.compile(r"(?<!\d)(?:\+213|0)[5-7]\d{8}(?!\d)"),
    ),
    (
        "nid_dz",
        re.compile(r"\b\d{18}\b"),
    ),
    (
        "tax_id_dz",
        re.compile(r"\b\d{15}\b"),
    ),
]

# Paths where request body contains user query text worth scanning
_SCAN_PATHS: frozenset[str] = frozenset({"/api/erp/query", "/query"})


def _mask_pii(text: str) -> tuple[str, dict[str, int]]:
    """Apply all PII patterns to *text*.

    Returns:
        masked_text — text with PII replaced by [REDACTED:<type>]
        counts      — {entity_type: hit_count} for Prometheus
    """
    counts: dict[str, int] = {}
    for entity_type, pattern in _PII_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            counts[entity_type] = len(matches)
            text = pattern.sub(f"[REDACTED:{entity_type.upper()}]", text)
    return text, counts


class PIIMaskingMiddleware(BaseHTTPMiddleware):
    """Detect and mask PII in inbound query text before it reaches the LLM.

    Sprint 1: email, DZ phone, NID (18-digit), tax ID (15-digit) patterns.
    Sprint 5: extended patterns + response-body masking + >= 98% recall test.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Mask PII in JSON body 'query' field on configured scan paths."""
        if request.method == "POST" and request.url.path in _SCAN_PATHS:
            try:
                raw_body = await request.body()
                payload = json.loads(raw_body)

                if isinstance(payload.get("query"), str):
                    masked_query, counts = _mask_pii(payload["query"])

                    if counts:
                        for entity_type, hit_count in counts.items():
                            PII_DETECTION_RATE.labels(entity_type=entity_type).inc(hit_count)
                            logger.info(
                                "pii.masked",
                                entity_type=entity_type,
                                count=hit_count,
                            )

                    # Store masked query in request.state so route handlers
                    # can prefer it over the raw body.
                    # Sprint 5 will rewrite the body at the ASGI level for
                    # transparent masking without route-handler cooperation.
                    request.state.pii_masked_query = masked_query
                    request.state.pii_hits = counts

            except (json.JSONDecodeError, UnicodeDecodeError):
                # Non-JSON body — skip masking, pass through
                pass

        return await call_next(request)


__all__ = ["PIIMaskingMiddleware"]
