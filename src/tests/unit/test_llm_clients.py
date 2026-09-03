"""
Unit tests — Sprint 8 Task 2: GeminiLLMClient and vLLMLLMClient.

All external I/O is mocked — no real API keys or network calls needed.

GeminiLLMClient:  unittest.mock.patch on google.genai.Client (created in __init__)
vLLMLLMClient:    unittest.mock.patch on httpx.Client (created inside complete())

Naming: test_{client}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.domain.ports.llm_port import LLMPort
from src.infrastructure.generation.gemini_llm_client import (
    _DEFAULT_MODEL,
    GeminiLLMClient,
)
from src.infrastructure.generation.vllm_llm_client import vLLMLLMClient

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_FAKE_KEY = "fake-gemini-key"
_FAKE_ANSWER = "The VAT rate for pharmaceutical products is 0%."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gemini_response(text: str | None) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


def _vllm_http_response(status_code: int = 200, answer: str = _FAKE_ANSWER) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = answer
    resp.json.return_value = {"choices": [{"message": {"content": answer}}]}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _make_gemini_client(answer: str | None = _FAKE_ANSWER, side_effect: Exception | None = None) -> GeminiLLMClient:
    """Build a GeminiLLMClient whose SDK call is mocked."""
    mock_sdk = MagicMock()
    if side_effect is not None:
        mock_sdk.models.generate_content.side_effect = side_effect
    else:
        mock_sdk.models.generate_content.return_value = _gemini_response(answer)
    with patch(
        "src.infrastructure.generation.gemini_llm_client.genai.Client",
        return_value=mock_sdk,
    ):
        client = GeminiLLMClient(api_key=_FAKE_KEY)
    # keep reference so callers can inspect calls
    client._mock_sdk = mock_sdk  # type: ignore[attr-defined]
    return client


def _make_vllm_client(base_url: str = "http://vllm-server", model: str = "mistral-7b") -> vLLMLLMClient:
    return vLLMLLMClient(base_url=base_url, model=model)


def _vllm_complete(
    client: vLLMLLMClient,
    prompt: str = "prompt",
    resp: MagicMock | None = None,
    side_effect: Exception | None = None,
) -> str:
    """Invoke client.complete() with a mocked httpx.Client context manager."""
    if resp is None:
        resp = _vllm_http_response()
    mock_http = MagicMock()
    if side_effect is not None:
        mock_http.post.side_effect = side_effect
    else:
        mock_http.post.return_value = resp
    with patch("src.infrastructure.generation.vllm_llm_client.httpx.Client") as cls:
        cls.return_value.__enter__.return_value = mock_http
        cls.return_value.__exit__.return_value = False
        return client.complete(prompt)


# ===========================================================================
# GeminiLLMClient — contract
# ===========================================================================

class TestGeminiLLMClientContract:

    def test_implements_llm_port(self):
        assert isinstance(_make_gemini_client(), LLMPort)

    def test_default_model_matches_the_module_default(self):
        """Assert against the constant, not a copy of its value.

        This test used to hard-code "gemini-2.5-flash-lite". Google retired
        that id — it now returns 404 "no longer available to new users" — and
        because the literal was duplicated here, the test kept passing while
        every real call failed. Tracking the constant means a stale default
        shows up as a live failure, not a green suite.
        """
        assert _make_gemini_client()._model == _DEFAULT_MODEL

    def test_custom_model_stored(self):
        with patch("src.infrastructure.generation.gemini_llm_client.genai.Client"):
            client = GeminiLLMClient(api_key=_FAKE_KEY, model="gemini-2.0-flash")
        assert client._model == "gemini-2.0-flash"

    def test_in_generation_package_all(self):
        from src.infrastructure.generation import GeminiLLMClient as _G
        assert _G is GeminiLLMClient


# ===========================================================================
# GeminiLLMClient — happy path
# ===========================================================================

class TestGeminiLLMClientHappyPath:

    def test_complete_returns_response_text(self):
        assert _make_gemini_client().complete("prompt") == _FAKE_ANSWER

    def test_complete_returns_string(self):
        assert isinstance(_make_gemini_client().complete("prompt"), str)

    def test_complete_empty_text_returns_empty_string(self):
        assert _make_gemini_client(answer="").complete("prompt") == ""

    def test_complete_none_text_returns_empty_string(self):
        assert _make_gemini_client(answer=None).complete("prompt") == ""

    def test_complete_passes_prompt_to_sdk(self):
        client = _make_gemini_client()
        client.complete("My specific prompt")
        args, kwargs = client._mock_sdk.models.generate_content.call_args
        assert "My specific prompt" in str(args) + str(kwargs)

    def test_complete_passes_temperature_in_config(self):
        client = _make_gemini_client()
        client.complete("prompt", temperature=0.7)
        _, kwargs = client._mock_sdk.models.generate_content.call_args
        assert kwargs["config"].temperature == 0.7

    def test_complete_passes_max_tokens_in_config(self):
        client = _make_gemini_client()
        client.complete("prompt", max_tokens=256)
        _, kwargs = client._mock_sdk.models.generate_content.call_args
        assert kwargs["config"].max_output_tokens == 256

    def test_complete_uses_correct_model(self):
        with patch("src.infrastructure.generation.gemini_llm_client.genai.Client") as cls:
            mock_sdk = MagicMock()
            mock_sdk.models.generate_content.return_value = _gemini_response("ok")
            cls.return_value = mock_sdk
            client = GeminiLLMClient(api_key=_FAKE_KEY, model="gemini-custom")
        client.complete("prompt")
        _, kwargs = mock_sdk.models.generate_content.call_args
        assert kwargs["model"] == "gemini-custom"


# ===========================================================================
# GeminiLLMClient — failure paths
# ===========================================================================

class TestGeminiLLMClientFailurePaths:

    def test_transport_error_raises_connection_error(self):
        client = _make_gemini_client(side_effect=httpx.TransportError("down"))
        with pytest.raises(ConnectionError, match="Gemini transport error"):
            client.complete("prompt")

    def test_server_500_raises_connection_error(self):
        client = _make_gemini_client(side_effect=RuntimeError("500 Internal Server Error"))
        with pytest.raises(ConnectionError, match="Gemini server error"):
            client.complete("prompt")

    def test_server_502_raises_connection_error(self):
        client = _make_gemini_client(side_effect=RuntimeError("502 Bad Gateway"))
        with pytest.raises(ConnectionError, match="Gemini server error"):
            client.complete("prompt")

    def test_server_503_raises_connection_error(self):
        client = _make_gemini_client(side_effect=RuntimeError("503 Service Unavailable"))
        with pytest.raises(ConnectionError, match="Gemini server error"):
            client.complete("prompt")

    def test_server_504_raises_connection_error(self):
        client = _make_gemini_client(side_effect=RuntimeError("504 Gateway Timeout"))
        with pytest.raises(ConnectionError, match="Gemini server error"):
            client.complete("prompt")

    def test_non_server_error_is_reraised_unchanged(self):
        client = _make_gemini_client(side_effect=ValueError("bad format"))
        with pytest.raises(ValueError, match="bad format"):
            client.complete("prompt")

    def test_401_not_converted_to_connection_error(self):
        client = _make_gemini_client(side_effect=RuntimeError("401 Unauthorized"))
        with pytest.raises(RuntimeError):
            client.complete("prompt")

    def test_transport_error_wraps_original_as_cause(self):
        original = httpx.TransportError("root cause")
        client = _make_gemini_client(side_effect=original)
        with pytest.raises(ConnectionError) as exc_info:
            client.complete("prompt")
        assert exc_info.value.__cause__ is original


# ===========================================================================
# GeminiLLMClient — from_env
# ===========================================================================

class TestGeminiLLMClientFromEnv:

    def test_from_env_default_model(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        with patch("src.infrastructure.generation.gemini_llm_client.genai.Client"):
            c = GeminiLLMClient.from_env()
        assert c._model == _DEFAULT_MODEL

    def test_from_env_custom_model(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
        with patch("src.infrastructure.generation.gemini_llm_client.genai.Client"):
            c = GeminiLLMClient.from_env()
        assert c._model == "gemini-2.0-flash"

    def test_from_env_raises_key_error_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(KeyError):
            GeminiLLMClient.from_env()


# ===========================================================================
# vLLMLLMClient — contract
# ===========================================================================

class TestVLLMClientContract:

    def test_implements_llm_port(self):
        assert isinstance(_make_vllm_client(), LLMPort)

    def test_trailing_slash_stripped_from_base_url(self):
        assert vLLMLLMClient(base_url="http://x/", model="m")._base_url == "http://x"

    def test_default_api_key_is_not_required(self):
        assert _make_vllm_client()._api_key == "not-required"

    def test_custom_api_key_stored(self):
        c = vLLMLLMClient(base_url="http://x", model="m", api_key="secret")
        assert c._api_key == "secret"

    def test_in_generation_package_all(self):
        from src.infrastructure.generation import vLLMLLMClient as _v
        assert _v is vLLMLLMClient


# ===========================================================================
# vLLMLLMClient — happy path
# ===========================================================================

class TestVLLMClientHappyPath:

    def test_complete_returns_answer_from_choices(self):
        assert _vllm_complete(_make_vllm_client()) == _FAKE_ANSWER

    def test_complete_returns_string(self):
        assert isinstance(_vllm_complete(_make_vllm_client()), str)

    def test_complete_posts_to_correct_endpoint(self):
        mock_http = MagicMock()
        mock_http.post.return_value = _vllm_http_response()
        with patch("src.infrastructure.generation.vllm_llm_client.httpx.Client") as cls:
            cls.return_value.__enter__.return_value = mock_http
            cls.return_value.__exit__.return_value = False
            _make_vllm_client(base_url="http://server").complete("p")
        url = mock_http.post.call_args[0][0]
        assert url == "http://server/v1/chat/completions"

    def test_complete_sends_model_in_payload(self):
        mock_http = MagicMock()
        mock_http.post.return_value = _vllm_http_response()
        with patch("src.infrastructure.generation.vllm_llm_client.httpx.Client") as cls:
            cls.return_value.__enter__.return_value = mock_http
            cls.return_value.__exit__.return_value = False
            _make_vllm_client(model="llama-3").complete("p")
        payload = mock_http.post.call_args[1]["json"]
        assert payload["model"] == "llama-3"

    def test_complete_sends_prompt_as_user_message(self):
        mock_http = MagicMock()
        mock_http.post.return_value = _vllm_http_response()
        with patch("src.infrastructure.generation.vllm_llm_client.httpx.Client") as cls:
            cls.return_value.__enter__.return_value = mock_http
            cls.return_value.__exit__.return_value = False
            _make_vllm_client().complete("my prompt")
        payload = mock_http.post.call_args[1]["json"]
        assert payload["messages"] == [{"role": "user", "content": "my prompt"}]

    def test_complete_sends_authorization_header(self):
        mock_http = MagicMock()
        mock_http.post.return_value = _vllm_http_response()
        client = vLLMLLMClient(base_url="http://x", model="m", api_key="my-key")
        with patch("src.infrastructure.generation.vllm_llm_client.httpx.Client") as cls:
            cls.return_value.__enter__.return_value = mock_http
            cls.return_value.__exit__.return_value = False
            client.complete("p")
        headers = mock_http.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-key"

    def test_complete_sends_temperature_in_payload(self):
        mock_http = MagicMock()
        mock_http.post.return_value = _vllm_http_response()
        with patch("src.infrastructure.generation.vllm_llm_client.httpx.Client") as cls:
            cls.return_value.__enter__.return_value = mock_http
            cls.return_value.__exit__.return_value = False
            _make_vllm_client().complete("p", temperature=0.5)
        payload = mock_http.post.call_args[1]["json"]
        assert payload["temperature"] == 0.5

    def test_complete_sends_max_tokens_in_payload(self):
        mock_http = MagicMock()
        mock_http.post.return_value = _vllm_http_response()
        with patch("src.infrastructure.generation.vllm_llm_client.httpx.Client") as cls:
            cls.return_value.__enter__.return_value = mock_http
            cls.return_value.__exit__.return_value = False
            _make_vllm_client().complete("p", max_tokens=1024)
        payload = mock_http.post.call_args[1]["json"]
        assert payload["max_tokens"] == 1024


# ===========================================================================
# vLLMLLMClient — failure paths
# ===========================================================================

class TestVLLMClientFailurePaths:

    def test_http_500_raises_connection_error(self):
        with pytest.raises(ConnectionError, match="vLLM returned 500"):
            _vllm_complete(_make_vllm_client(), resp=_vllm_http_response(500))

    def test_http_502_raises_connection_error(self):
        with pytest.raises(ConnectionError, match="vLLM returned 502"):
            _vllm_complete(_make_vllm_client(), resp=_vllm_http_response(502))

    def test_http_503_raises_connection_error(self):
        with pytest.raises(ConnectionError, match="vLLM returned 503"):
            _vllm_complete(_make_vllm_client(), resp=_vllm_http_response(503))

    def test_http_504_raises_connection_error(self):
        with pytest.raises(ConnectionError, match="vLLM returned 504"):
            _vllm_complete(_make_vllm_client(), resp=_vllm_http_response(504))

    def test_connect_error_raises_connection_error(self):
        with pytest.raises(ConnectionError, match="vLLM transport error"):
            _vllm_complete(_make_vllm_client(), side_effect=httpx.ConnectError("refused"))

    def test_timeout_raises_connection_error(self):
        with pytest.raises(ConnectionError, match="vLLM transport error"):
            _vllm_complete(_make_vllm_client(), side_effect=httpx.TimeoutException("timed out"))

    def test_read_timeout_raises_connection_error(self):
        with pytest.raises(ConnectionError, match="vLLM transport error"):
            _vllm_complete(_make_vllm_client(), side_effect=httpx.ReadTimeout("read timeout"))

    def test_transport_error_wraps_original_as_cause(self):
        original = httpx.ConnectError("root cause")
        with pytest.raises(ConnectionError) as exc_info:
            _vllm_complete(_make_vllm_client(), side_effect=original)
        assert exc_info.value.__cause__ is original

    def test_http_404_reraises_via_raise_for_status(self):
        with pytest.raises(httpx.HTTPStatusError):
            _vllm_complete(_make_vllm_client(), resp=_vllm_http_response(404))


# ===========================================================================
# vLLMLLMClient — from_env
# ===========================================================================

class TestVLLMClientFromEnv:

    def test_from_env_reads_base_url_and_model(self, monkeypatch):
        monkeypatch.setenv("VLLM_BASE_URL", "http://my-vllm")
        monkeypatch.setenv("VLLM_MODEL", "llama-3")
        monkeypatch.delenv("VLLM_API_KEY", raising=False)
        c = vLLMLLMClient.from_env()
        assert c._base_url == "http://my-vllm"
        assert c._model == "llama-3"

    def test_from_env_default_api_key_is_not_required(self, monkeypatch):
        monkeypatch.setenv("VLLM_BASE_URL", "http://x")
        monkeypatch.setenv("VLLM_MODEL", "m")
        monkeypatch.delenv("VLLM_API_KEY", raising=False)
        assert vLLMLLMClient.from_env()._api_key == "not-required"

    def test_from_env_reads_custom_api_key(self, monkeypatch):
        monkeypatch.setenv("VLLM_BASE_URL", "http://x")
        monkeypatch.setenv("VLLM_MODEL", "m")
        monkeypatch.setenv("VLLM_API_KEY", "bearer-secret")
        assert vLLMLLMClient.from_env()._api_key == "bearer-secret"

    def test_from_env_raises_key_error_if_base_url_missing(self, monkeypatch):
        monkeypatch.delenv("VLLM_BASE_URL", raising=False)
        monkeypatch.setenv("VLLM_MODEL", "m")
        with pytest.raises(KeyError):
            vLLMLLMClient.from_env()

    def test_from_env_raises_key_error_if_model_missing(self, monkeypatch):
        monkeypatch.setenv("VLLM_BASE_URL", "http://x")
        monkeypatch.delenv("VLLM_MODEL", raising=False)
        with pytest.raises(KeyError):
            vLLMLLMClient.from_env()
