"""QueryClassifierAgent — LLM-backed implementation of QueryClassifierPort.

Loads ``classifier_v1`` from the PromptRegistry, injects the query (and an
optional ERP module hint) into the prompt, calls the LLM, and parses the
returned JSON into a ``RoutingDecision``.

Error contract:
  - ``ValueError``  — LLM returned non-JSON or JSON that fails the schema.
  - Any ``LLMUnavailableError`` from the LLM bubbles up unchanged so the
    caller can activate degraded mode.
"""
from __future__ import annotations

import json

import jsonschema

from src.domain.erp_module import ErpModule
from src.domain.models.routing_decision import RoutingDecision
from src.domain.ports.llm_port import LLMPort
from src.domain.ports.query_classifier_port import QueryClassifierPort
from src.domain.query_intent import QueryIntent
from src.observability.structured_logger import get_logger
from src.prompts.registry import PromptRegistry

logger = get_logger(__name__)


class QueryClassifierAgent(QueryClassifierPort):
    """Classify an ERP query by calling an LLM with a versioned prompt.

    Args:
        llm: Any ``LLMPort`` implementation (Gemini, vLLM, or ModelSelector).
        registry: ``PromptRegistry`` pointed at ``src/prompts``.
    """

    def __init__(self, llm: LLMPort, registry: PromptRegistry) -> None:
        self._llm = llm
        self._registry = registry

    # ------------------------------------------------------------------
    # QueryClassifierPort implementation
    # ------------------------------------------------------------------

    def classify(self, query: str, erp_module: str | None = None) -> RoutingDecision:
        """Return a ``RoutingDecision`` for *query*.

        Args:
            query: The raw natural-language query from the user.
            erp_module: Optional ERP domain hint (e.g. ``"finance"``).
                        Injected into the prompt as additional context.

        Returns:
            A ``RoutingDecision`` with intent, confidence, erp_module, and reason.

        Raises:
            ValueError: If the LLM response is not valid JSON or fails schema
                        validation.
        """
        logger.info(
            "classifier.classify",
            query_preview=query[:80],
            erp_module=erp_module,
        )

        prompt_version = self._registry.resolve("classifier", "production")
        prompt = self._build_prompt(prompt_version.prompt_text, query, erp_module)

        raw = self._llm.complete(
            prompt,
            temperature=prompt_version.parameters.temperature,
            max_tokens=prompt_version.parameters.max_tokens,
        )

        parsed = self._parse_and_validate(raw, prompt_version)

        intent = QueryIntent(parsed["intent"])
        module = self._resolve_module(erp_module)

        decision = RoutingDecision(
            intent=intent,
            confidence=float(parsed["confidence"]),
            erp_module=module,
            reason=parsed["reason"],
        )

        logger.info(
            "classifier.result",
            intent=decision.intent.value,
            confidence=decision.confidence,
            erp_module=module.value if module else None,
        )

        return decision

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        template: str, query: str, erp_module: str | None
    ) -> str:
        """Substitute ``{{query}}`` and ``{{erp_module}}`` placeholders."""
        module_hint = erp_module or "not specified"
        return (
            template
            .replace("{{query}}", query)
            .replace("{{erp_module}}", module_hint)
        )

    def _parse_and_validate(self, raw: str, prompt_version) -> dict:
        """Parse *raw* as JSON and validate against the prompt's schema."""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"classifier returned non-JSON response: {raw!r}"
            ) from exc

        try:
            self._registry.validate_output(prompt_version, parsed)
        except jsonschema.ValidationError as exc:
            raise ValueError(
                f"classifier output failed schema validation: {exc.message}"
            ) from exc

        return parsed

    @staticmethod
    def _resolve_module(erp_module: str | None) -> ErpModule | None:
        """Convert an ``erp_module`` string to an ``ErpModule`` enum, or ``None``."""
        if erp_module is None:
            return None
        try:
            return ErpModule(erp_module.lower())
        except ValueError:
            return None


__all__ = ["QueryClassifierAgent"]
