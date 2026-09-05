"""
Parsing LLM responses that are supposed to be JSON but are not quite.

Lives with the LLM infrastructure rather than under src/agents/ because the
SQL generator needs it too, and src/agents/__init__ eagerly imports every
agent — so importing a helper from there pulled the whole agent layer in and
closed a cycle back through sql_agent to query_generator.

Every agent asks its model for a JSON object and called ``json.loads`` on the
reply directly. Gemini wraps JSON in a markdown fence:

    ```json
    {"grounded": false, "answer": null, ...}
    ```

so the parse failed with ``Expecting value: line 1 column 1 (char 0)`` on
every single request. RAGAgent turned that into ``RAGResult.not_grounded()``,
which is indistinguishable from the model honestly reporting that it could not
answer — so a retrieval pipeline that was working correctly, with real chunks
and a real context window, reported "not grounded" every time.

Instructing the model harder is not a fix. Fenced output is normal behaviour
for several providers, it varies between models and between calls, and the
failure is silent. Accepting it at the boundary is.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE_OPEN = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n?")
_FENCE_CLOSE = re.compile(r"\n?\s*```\s*$")


def strip_code_fence(text: str) -> str:
    """Remove a leading ```json (or ```) fence and its closing counterpart."""
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    cleaned = _FENCE_OPEN.sub("", cleaned)
    cleaned = _FENCE_CLOSE.sub("", cleaned)
    return cleaned.strip()


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Return the JSON object in *raw*, tolerating a markdown fence.

    Raises:
        ValueError: the response is empty, or holds no parseable JSON object.
            Raised rather than returned as None so callers keep one failure
            path — every agent already treats an exception here as "the model
            did not answer usefully".
    """
    if not raw or not raw.strip():
        raise ValueError("LLM returned an empty response")

    cleaned = strip_code_fence(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Prose around the JSON is the other common shape ("Here is the
        # result: {...}"). Fall back to the outermost braced span.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"No JSON object found in LLM response: {raw[:200]!r}") from None
        try:
            parsed = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON in LLM response: {raw[:200]!r}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"LLM response is {type(parsed).__name__}, expected an object")
    return parsed


__all__ = ["parse_llm_json", "strip_code_fence"]
