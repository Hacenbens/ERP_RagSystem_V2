"""Generation package — concrete LLM client implementations.

Implementations of ``LLMPort`` that delegate to real language model providers:
  - ``OpenAILLMClient``  — calls the OpenAI chat-completions API
  - ``vLLMLLMClient``    — calls a self-hosted vLLM OpenAI-compatible endpoint via httpx

Both raise ``ConnectionError`` on network failures or 5xx responses so that
``ModelSelector`` can apply its circuit-breaker and fallback logic uniformly.
"""
from __future__ import annotations

from src.infrastructure.generation.gemini_llm_client import GeminiLLMClient
from src.infrastructure.generation.vllm_llm_client import vLLMLLMClient

__all__ = ["GeminiLLMClient", "vLLMLLMClient"]
