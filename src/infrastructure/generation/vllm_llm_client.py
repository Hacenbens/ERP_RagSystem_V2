"""vLLMLLMClient — LLMPort implementation for a self-hosted vLLM endpoint.

vLLM exposes an OpenAI-compatible HTTP API, so this client sends a JSON
payload to ``POST /v1/chat/completions`` via ``httpx`` (no vllm Python
package required — only a running vLLM server reachable at ``base_url``).

Raises ``ConnectionError`` on transport failures and non-2xx HTTP responses
so that ``ModelSelector`` can apply its circuit-breaker policy uniformly.
"""
from __future__ import annotations

import os

import httpx

from src.domain.ports.llm_port import LLMPort
from src.observability.stage_timer import record_tokens
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_COMPLETIONS_PATH = "/v1/chat/completions"


class vLLMLLMClient(LLMPort):
    """Call a self-hosted vLLM server (OpenAI-compatible API) for text completions.

    Constructor arguments are injected by the DI container; callers must
    resolve environment variables themselves (or use ``from_env()``).

    Raises:
        ConnectionError: on ``httpx`` transport errors or HTTP 5xx responses.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "not-required",
        timeout_s: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout_s = timeout_s

    @classmethod
    def from_env(cls) -> "vLLMLLMClient":
        """Construct from standard environment variables.

        Reads ``VLLM_BASE_URL``, ``VLLM_MODEL``, and optional ``VLLM_API_KEY``.
        """
        return cls(
            base_url=os.environ["VLLM_BASE_URL"],
            model=os.environ["VLLM_MODEL"],
            api_key=os.environ.get("VLLM_API_KEY", "not-required"),
        )

    def complete(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Return a text completion from the vLLM server.

        Raises:
            ConnectionError: on network errors or HTTP 5xx responses.
        """
        logger.info(
            "vllm_llm.complete.start",
            base_url=self._base_url,
            model=self._model,
            prompt_len=len(prompt),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                response = client.post(
                    f"{self._base_url}{_COMPLETIONS_PATH}",
                    json=payload,
                    headers=headers,
                )

            if response.status_code >= 500:
                logger.error(
                    "vllm_llm.complete.server_error",
                    status_code=response.status_code,
                    body=response.text[:200],
                )
                raise ConnectionError(
                    f"vLLM returned {response.status_code}: {response.text[:200]}"
                )

            response.raise_for_status()
            data = response.json()
            answer: str = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            record_tokens("vllm", prompt_tokens, completion_tokens)
            logger.info(
                "vllm_llm.complete.done",
                model=self._model,
                answer_len=len(answer),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            return answer

        except httpx.TransportError as exc:
            logger.error("vllm_llm.complete.transport_error", error=str(exc))
            raise ConnectionError(f"vLLM transport error: {exc}") from exc


__all__ = ["vLLMLLMClient"]
