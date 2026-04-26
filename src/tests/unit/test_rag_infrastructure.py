"""
Unit tests for Sprint 7 RAG reranker and context builder infrastructure.
"""
from __future__ import annotations

import httpx

from src.domain.models.scored_chunk import ScoredChunk
from src.infrastructure.rag.context_builder import ContextBuilder
from src.infrastructure.rag.reranker import CrossEncoderReranker, IdentityReranker


def _chunk(
    chunk_id: str,
    score: float,
    content: str,
    source: str = "doc.pdf",
) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        content=content,
        score=score,
        source=source,
        erp_module="finance",
    )


class TestIdentityReranker:
    def test_rerank_returns_score_descending_top_k(self) -> None:
        reranker = IdentityReranker()
        docs = [
            _chunk("c-low", 0.20, "low"),
            _chunk("c-high", 0.95, "high"),
            _chunk("c-mid", 0.50, "mid"),
        ]

        ranked = reranker.rerank(query="vat", docs=docs, top_k=2)

        assert [doc.chunk_id for doc in ranked] == ["c-high", "c-mid"]


class TestCrossEncoderReranker:
    def test_rerank_uses_predictor_scores(self) -> None:
        def predictor(pairs: list[list[str]]) -> list[float]:
            assert pairs == [
                ["vat", "first"],
                ["vat", "second"],
                ["vat", "third"],
            ]
            return [0.10, 0.99, 0.55]

        reranker = CrossEncoderReranker(predictor=predictor)
        docs = [
            _chunk("c-1", 0.80, "first"),
            _chunk("c-2", 0.70, "second"),
            _chunk("c-3", 0.60, "third"),
        ]

        ranked = reranker.rerank(query="vat", docs=docs, top_k=2)

        assert [doc.chunk_id for doc in ranked] == ["c-2", "c-3"]
        assert ranked[0].score == 0.99

    def test_rerank_falls_back_to_identity_when_predictor_unavailable(self) -> None:
        reranker = CrossEncoderReranker(predictor=None)
        docs = [
            _chunk("c-1", 0.30, "first"),
            _chunk("c-2", 0.90, "second"),
        ]

        ranked = reranker.rerank(query="vat", docs=docs, top_k=2)

        assert [doc.chunk_id for doc in ranked] == ["c-2", "c-1"]

    def test_rerank_calls_ngrok_endpoint(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = request.read().decode("utf-8")
            return httpx.Response(200, json={"scores": [0.15, 0.95, 0.55]})

        reranker = CrossEncoderReranker(
            predictor=None,
            base_url="https://example.ngrok.app",
            endpoint="/rerank",
            api_key="secret",
            transport=httpx.MockTransport(handler),
        )
        docs = [
            _chunk("c-1", 0.80, "first"),
            _chunk("c-2", 0.70, "second"),
            _chunk("c-3", 0.60, "third"),
        ]

        ranked = reranker.rerank(query="vat", docs=docs, top_k=2)

        assert [doc.chunk_id for doc in ranked] == ["c-2", "c-3"]
        assert captured["path"] == "/rerank"
        assert '"query":"vat"' in str(captured["json"]).replace(" ", "")
        assert '"documents":["first","second","third"]' in str(captured["json"]).replace(" ", "")

    def test_rerank_supports_indexed_result_shape(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                json={"results": [{"index": 0, "score": 0.2}, {"index": 1, "score": 0.9}]},
            )

        reranker = CrossEncoderReranker(
            predictor=None,
            base_url="https://example.ngrok.app",
            transport=httpx.MockTransport(handler),
        )
        docs = [_chunk("c-1", 0.3, "first"), _chunk("c-2", 0.4, "second")]

        ranked = reranker.rerank(query="vat", docs=docs, top_k=2)

        assert [doc.chunk_id for doc in ranked] == ["c-2", "c-1"]

    def test_rerank_falls_back_to_identity_on_http_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(503, json={"detail": "unavailable"})

        reranker = CrossEncoderReranker(
            predictor=None,
            base_url="https://example.ngrok.app",
            transport=httpx.MockTransport(handler),
        )
        docs = [_chunk("c-1", 0.3, "first"), _chunk("c-2", 0.9, "second")]

        ranked = reranker.rerank(query="vat", docs=docs, top_k=2)

        assert [doc.chunk_id for doc in ranked] == ["c-2", "c-1"]

    def test_rerank_empty_docs_returns_empty_list(self) -> None:
        reranker = CrossEncoderReranker(predictor=lambda pairs: [1.0] * len(pairs))

        ranked = reranker.rerank(query="vat", docs=[], top_k=5)

        assert ranked == []

    def test_rerank_falls_back_when_results_list_has_wrong_count(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                json={"results": [{"index": 0, "score": 0.9}]},
            )

        reranker = CrossEncoderReranker(
            predictor=None,
            base_url="https://example.ngrok.app",
            transport=httpx.MockTransport(handler),
        )
        docs = [_chunk("c-1", 0.3, "first"), _chunk("c-2", 0.8, "second")]

        ranked = reranker.rerank(query="vat", docs=docs, top_k=2)

        assert [doc.chunk_id for doc in ranked] == ["c-2", "c-1"]


class TestContextBuilder:
    def test_build_formats_chunks_in_expected_layout(self) -> None:
        builder = ContextBuilder()
        chunks = [
            _chunk("c-1", 0.91234, "VAT rate is 9%.", source="tax.pdf"),
            _chunk("c-2", 0.50001, "Quarterly count is 42.", source="erp.sql"),
        ]

        context = builder.build(chunks, max_tokens=100)

        assert "[c-1] (score=0.9123, source=tax.pdf)" in context
        assert "VAT rate is 9%." in context
        assert "[c-2] (score=0.5000, source=erp.sql)" in context
        assert context.endswith("\n\n")

    def test_build_truncates_when_token_budget_exceeded(self) -> None:
        builder = ContextBuilder()
        chunks = [
            _chunk("c-1", 0.9, "A" * 20),
            _chunk("c-2", 0.8, "B" * 20),
        ]

        context = builder.build(chunks, max_tokens=15)

        assert "[c-1]" in context
        assert "[c-2]" not in context

    def test_build_returns_empty_string_for_no_chunks(self) -> None:
        builder = ContextBuilder()

        context = builder.build([], max_tokens=10)

        assert context == ""
