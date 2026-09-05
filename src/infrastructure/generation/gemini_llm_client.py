"""GeminiLLMClient — LLMPort implementation backed by Google Gemini API.

Uses ``google-genai`` (the current SDK).  API key is read from the
``GEMINI_API_KEY`` environment variable (or passed directly to the
constructor for DI); the model comes from ``GEMINI_MODEL``.

Google retires model ids. ``gemini-2.5-flash-lite`` — the previous default —
now returns 404 "no longer available to new users", which is a client error
rather than a transport failure, so pin a current id and keep
``GEMINI_MODEL`` in .env pointing at one. ``gemini-flash-lite-latest`` is
the moving alias if you would rather not pin.

Raises ``ConnectionError`` on transport failures and non-2xx HTTP errors so
that ``ModelSelector`` can apply its circuit-breaker policy uniformly.
"""
from __future__ import annotations

import os

import httpx
from google import genai
from google.genai import types

from src.domain.ports.llm_port import LLMPort
from src.observability.stage_timer import record_tokens
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _usage(response: object) -> tuple[int | None, int | None]:
    """Read the token counts Gemini reported, or (None, None) if it did not.

    Every field is optional in the SDK's own typing, and the shape has moved
    between versions, so this reads defensively rather than indexing. None
    means "not reported" — recording it as 0 would claim a free call.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None, None
    return (
        getattr(usage, "prompt_token_count", None),
        getattr(usage, "candidates_token_count", None),
    )


class GeminiLLMClient(LLMPort):
    """Call the Google Gemini API (free tier) to generate text completions.

    Constructor arguments are injected by the DI container; callers must
    resolve environment variables themselves (or use ``from_env()``).

    Raises:
        ConnectionError: on network failures or HTTP 5xx responses, so that
            ``ModelSelector`` can apply its circuit-breaker policy uniformly.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        timeout_s: float = 30.0,
    ) -> None:
        self._model = model
        self._timeout_s = timeout_s
        self._client = genai.Client(api_key=api_key)

    @classmethod
    def from_env(cls) -> "GeminiLLMClient":
        """Construct from standard environment variables.

        Reads ``GEMINI_API_KEY`` and optional ``GEMINI_MODEL``
        (default ``gemini-2.5-flash-lite``).
        """
        return cls(
            api_key=os.environ["GEMINI_API_KEY"],
            model=os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL),
        )

    def complete(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Return a text completion from the Gemini API.

        Raises:
            ConnectionError: on ``httpx`` transport errors or HTTP 5xx responses.
        """
        logger.info(
            "gemini_llm.complete.start",
            model=self._model,
            prompt_len=len(prompt),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            answer: str = response.text or ""
            prompt_tokens, completion_tokens = _usage(response)
            record_tokens("gemini", prompt_tokens, completion_tokens)
            logger.info(
                "gemini_llm.complete.done",
                model=self._model,
                answer_len=len(answer),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            return answer

        except httpx.TransportError as exc:
            logger.error("gemini_llm.complete.transport_error", error=str(exc))
            raise ConnectionError(f"Gemini transport error: {exc}") from exc

        except Exception as exc:
            # google-genai raises google.api_core.exceptions.* on HTTP errors;
            # catching by status code string is the most portable approach.
            msg = str(exc)
            logger.error("gemini_llm.complete.error", error=msg)
            if any(code in msg for code in ("500", "502", "503", "504")):
                raise ConnectionError(f"Gemini server error: {exc}") from exc
            raise


__all__ = ["GeminiLLMClient"]
