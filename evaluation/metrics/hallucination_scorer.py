"""
Hallucination Scorer — Sprint 2
LLM-as-judge: given an (answer, context) pair, returns a grounding_score in [0.0, 1.0].
Score 1.0 = fully grounded in context, 0.0 = entirely hallucinated.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

HALLUCINATION_MAX = float(os.environ.get("HALLUCINATION_MAX", "0.05"))

# Judge prompt template — zero-shot, chain-of-thought
_JUDGE_PROMPT = """\
You are a strict factual grounding evaluator. Your job is to assess whether \
the given answer is fully supported by the provided context.

CONTEXT:
{context}

ANSWER:
{answer}

Instructions:
1. Read the context carefully.
2. Check every factual claim in the answer against the context.
3. A claim is GROUNDED if it can be directly inferred from the context.
4. A claim is HALLUCINATED if it adds information not present in the context.
5. Output your evaluation as JSON with this exact structure:
{{
  "grounding_score": <float 0.0 to 1.0>,
  "grounded_claims": <int>,
  "hallucinated_claims": <int>,
  "reasoning": "<one sentence>"
}}

Output ONLY the JSON. No preamble.
"""


@dataclass
class HallucinationResult:
    grounding_score: float        # 1.0 = fully grounded, 0.0 = fully hallucinated
    hallucination_rate: float     # 1.0 - grounding_score
    grounded_claims: int
    hallucinated_claims: int
    reasoning: str
    is_acceptable: bool           # True if hallucination_rate <= HALLUCINATION_MAX


def score(answer: str, context: str, llm_client=None) -> HallucinationResult:
    """
    Score hallucination in `answer` given `context`.

    Args:
        answer: The LLM-generated answer to evaluate.
        context: The retrieved context chunks used to generate the answer.
        llm_client: Optional LLM client (must have .complete(prompt) -> str).
                    If None, falls back to heuristic scorer.

    Returns:
        HallucinationResult with grounding_score in [0.0, 1.0].
    """
    if llm_client is not None:
        return _llm_judge(answer, context, llm_client)
    return _heuristic_score(answer, context)


def _llm_judge(answer: str, context: str, llm_client) -> HallucinationResult:
    """Use LLM-as-judge to score grounding."""
    import json

    prompt = _JUDGE_PROMPT.format(answer=answer, context=context)
    raw = llm_client.complete(prompt)

    # Extract JSON from the response
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        raise ValueError(f"LLM judge returned non-JSON response: {raw[:200]}")

    data = json.loads(json_match.group())
    grounding_score = float(data["grounding_score"])
    grounded = int(data.get("grounded_claims", 0))
    hallucinated = int(data.get("hallucinated_claims", 0))
    reasoning = str(data.get("reasoning", ""))

    return _build_result(grounding_score, grounded, hallucinated, reasoning)


def _heuristic_score(answer: str, context: str) -> HallucinationResult:
    """
    Offline heuristic fallback: token overlap between answer and context.
    Used when no LLM client is available (unit tests, CI without API keys).
    """
    def tokenize(text: str) -> set[str]:
        return set(re.findall(r"\b\w{4,}\b", text.lower()))

    answer_tokens = tokenize(answer)
    context_tokens = tokenize(context)

    if not answer_tokens:
        return _build_result(1.0, 0, 0, "Empty answer — trivially grounded")

    overlap = answer_tokens & context_tokens
    grounding_score = len(overlap) / len(answer_tokens)
    grounded = len(overlap)
    hallucinated = len(answer_tokens - context_tokens)

    return _build_result(
        grounding_score,
        grounded,
        hallucinated,
        f"Heuristic: {grounded}/{len(answer_tokens)} answer tokens found in context",
    )


def _build_result(
    grounding_score: float,
    grounded: int,
    hallucinated: int,
    reasoning: str,
) -> HallucinationResult:
    grounding_score = max(0.0, min(1.0, grounding_score))
    hallucination_rate = 1.0 - grounding_score
    return HallucinationResult(
        grounding_score=grounding_score,
        hallucination_rate=hallucination_rate,
        grounded_claims=grounded,
        hallucinated_claims=hallucinated,
        reasoning=reasoning,
        is_acceptable=hallucination_rate <= HALLUCINATION_MAX,
    )
