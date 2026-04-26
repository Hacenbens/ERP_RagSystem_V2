from __future__ import annotations

import os
from typing import Any

import httpx

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
        self._base_url = (base_url or os.environ.get("NGROK_BASE_URL", "")).rstrip("/")
        self._endpoint = endpoint or os.environ.get("NGROK_EMBEDDING_ENDPOINT", "/embed")
        self._model = model or os.environ.get("NGROK_EMBEDDING_MODEL", "")
        self._api_key = api_key or os.environ.get("NGROK_API_KEY", "")
        self._timeout_s = timeout_s
        self._transport = transport

    def embed(self, text: str) -> list[float]:
        """Return an embedding vector for *text* from the remote ngrok service."""
        if not self._base_url:
            raise RuntimeError("NGROK_BASE_URL is not configured for embeddings")

        payload: dict[str, Any] = {"texts": [text]}
        if self._model:
            payload["model"] = self._model

        with httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout_s,
            transport=self._transport,
        ) as client:
            response = client.post(self._endpoint, json=payload, headers=self._headers())
            response.raise_for_status()
            data = response.json()

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
    """Fallback test provider that returns a fixed-size zero vector."""

    def embed(self, text: str) -> list[float]:
        """Return a deterministic zero vector without calling any external model."""
        del text
        return [0.0] * 768


__all__ = ["NgrokEmbeddingProvider", "NoopEmbeddingProvider"]
