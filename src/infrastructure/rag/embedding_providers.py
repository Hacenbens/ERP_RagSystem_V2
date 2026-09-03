from __future__ import annotations

import os
from typing import Any

import httpx

from src.domain.exceptions import EmbeddingUnavailableError
from src.domain.ports.embedding_port import EmbeddingPort
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


class NgrokEmbeddingProvider(EmbeddingPort):
    """Embedding provider backed by an ngrok-exposed HTTP inference service."""

    def __init__(
        self,
        base_url: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # `is None` rather than `or`: an explicitly-passed "" means "no base
        # URL", but `or` treated it as unset and silently read the ambient
        # environment. A unit test that constructed the provider with
        # base_url="" to assert the misconfiguration path therefore picked up
        # the developer's real .env and made a live HTTPS call.
        self._base_url = (
            os.environ.get("NGROK_BASE_URL", "") if base_url is None else base_url
        ).rstrip("/")
        self._endpoint = (
            os.environ.get("NGROK_EMBEDDING_ENDPOINT", "/embed") if endpoint is None else endpoint
        )
        self._model = os.environ.get("NGROK_EMBEDDING_MODEL", "") if model is None else model
        self._api_key = os.environ.get("NGROK_API_KEY", "") if api_key is None else api_key
        self._timeout_s = timeout_s
        self._transport = transport

    def embed(self, text: str) -> list[float]:
        """Return an embedding vector for *text* from the remote ngrok service."""
        if not self._base_url:
            raise EmbeddingUnavailableError(
                "NGROK_BASE_URL is not configured for embeddings"
            )

        payload: dict[str, Any] = {"texts": [text]}
        if self._model:
            payload["model"] = self._model

        # Transport and HTTP errors become EmbeddingUnavailableError so the
        # retriever can degrade. Unwrapped, an httpx.HTTPStatusError from a
        # dead tunnel travelled through VectorRetriever and RAGAgent
        # uncaught and surfaced as a 500 on every RAG query.
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout_s,
                transport=self._transport,
            ) as client:
                response = client.post(self._endpoint, json=payload, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(
                f"Embedding service at {self._base_url} failed: {exc}"
            ) from exc

        embedding = self._parse_embedding(data)
        logger.info(
            "rag.embedding.done",
            endpoint=self._endpoint,
            dimensions=len(embedding),
        )
        return embedding

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "ngrok-skip-browser-warning": "true",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _parse_embedding(self, payload: dict[str, Any]) -> list[float]:
        # Server contract: {"embeddings": [[float, ...]]}
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            return [float(v) for v in embeddings[0]]

        raise RuntimeError(
            f"Embedding endpoint returned unsupported shape — keys: {list(payload.keys())}"
        )


class NoopEmbeddingProvider(EmbeddingPort):
    """Placeholder used when no embedding provider is configured.

    It refuses rather than returning a zero vector. A zero vector has no
    direction, so cosine similarity against it is 0.0 for every stored chunk:
    retrieval returns an arbitrary k documents, the reranker faithfully
    orders meaningless scores, and the LLM cites them. That is worse than an
    outage, because it looks like a working answer.
    """

    def embed(self, text: str) -> list[float]:
        """Always raise — there is no provider to embed with."""
        del text
        raise EmbeddingUnavailableError(
            "No embedding provider configured — set NGROK_BASE_URL. "
            "Retrieval is unavailable; answers cannot be grounded."
        )


__all__ = ["NgrokEmbeddingProvider", "NoopEmbeddingProvider"]
