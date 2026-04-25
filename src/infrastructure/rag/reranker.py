from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import httpx

from src.domain.models.scored_chunk import ScoredChunk
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_Predictor = Callable[[list[list[str]]], list[float]]


class IdentityReranker:
    """No-op reranker that preserves score-based ordering."""

    def rerank(
        self,
        query: str,
        docs: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        """Return the highest-scoring documents without model-based reranking."""
        del query
        ranked = sorted(docs, key=lambda doc: doc.score, reverse=True)
        return ranked[:top_k]


class CrossEncoderReranker:
    """Cross-encoder reranker backed by ngrok, with graceful local fallback."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        predictor: _Predictor | None = None,
        base_url: str | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model_name = model_name
        self._predictor = predictor
        self._base_url = (base_url or os.environ.get("NGROK_BASE_URL", "")).rstrip("/")
        self._endpoint = endpoint or os.environ.get("NGROK_RERANKER_ENDPOINT", "/rerank")
        self._api_key = api_key or os.environ.get("NGROK_API_KEY", "")
        self._timeout_s = timeout_s
        self._transport = transport

    def rerank(
        self,
        query: str,
        docs: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        """Return the top-k documents after cross-encoder rescoring."""
        if not docs or top_k <= 0:
            return []

        try:
            scores = self._score(query=query, docs=docs)
        except RuntimeError as exc:
            logger.error(
                "rag.reranker.misconfigured",
                model_name=self._model_name,
                reason=str(exc),
            )
            return IdentityReranker().rerank(query=query, docs=docs, top_k=top_k)
        except Exception as exc:
            logger.warning(
                "rag.reranker.fallback",
                model_name=self._model_name,
                reason=str(exc),
            )
            return IdentityReranker().rerank(query=query, docs=docs, top_k=top_k)

        rescored = sorted(
            (
                ScoredChunk(
                    chunk_id=doc.chunk_id,
                    content=doc.content,
                    score=float(score),
                    source=doc.source,
                    erp_module=doc.erp_module,
                )
                for doc, score in zip(docs, scores, strict=True)
            ),
            key=lambda doc: doc.score,
            reverse=True,
        )
        logger.info(
            "rag.reranker.done",
            model_name=self._model_name,
            input_docs=len(docs),
            output_docs=min(len(rescored), top_k),
        )
        return rescored[:top_k]

    def _score(self, query: str, docs: list[ScoredChunk]) -> list[float]:
        if self._predictor is not None:
            pairs = [[query, doc.content] for doc in docs]
            return self._predictor(pairs)

        if not self._base_url:
            raise RuntimeError("NGROK_BASE_URL is not configured for reranking")

        payload: dict[str, Any] = {
            "query": query,
            "documents": [doc.content for doc in docs],
            "top_k": len(docs),
        }
        if self._model_name:
            payload["model"] = self._model_name

        with httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout_s,
            transport=self._transport,
        ) as client:
            response = client.post(self._endpoint, json=payload, headers=self._headers())
            response.raise_for_status()
            return self._parse_scores(response.json(), expected=len(docs))

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "ngrok-skip-browser-warning": "true",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _parse_scores(self, payload: dict[str, Any], expected: int) -> list[float]:
        if "scores" in payload and isinstance(payload["scores"], list):
            scores = [float(value) for value in payload["scores"]]
        else:
            results = payload.get("results")
            if not isinstance(results, list):
                raise RuntimeError("Reranker endpoint returned an unsupported response shape")
            indexed_scores = [
                (
                    int(item["index"]),
                    float(item["score"]),
                )
                for item in results
                if isinstance(item, dict) and "index" in item and "score" in item
            ]
            if len(indexed_scores) != expected:
                raise RuntimeError("Reranker endpoint returned incomplete scores")
            indexed_scores.sort(key=lambda item: item[0])
            scores = [score for _, score in indexed_scores]

        if len(scores) != expected:
            raise RuntimeError("Reranker endpoint returned unexpected score count")
        return scores


__all__ = ["CrossEncoderReranker", "IdentityReranker"]
