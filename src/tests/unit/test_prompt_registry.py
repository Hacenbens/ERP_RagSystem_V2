"""Unit tests for PromptRegistry — Sprint 7 Task 5."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from src.prompts.registry import (
    PromptNotFoundError,
    PromptRegistry,
    PromptVersion,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


@pytest.fixture()
def registry() -> PromptRegistry:
    return PromptRegistry(PROMPTS_DIR)


def _make_registry(tmp_path: Path, yaml_body: str) -> PromptRegistry:
    """Write a single YAML file in a temp prompts dir and return the registry."""
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    (versions_dir / "test_v1.yaml").write_text(yaml_body)
    return PromptRegistry(tmp_path)


# ---------------------------------------------------------------------------
# resolve — happy path
# ---------------------------------------------------------------------------

class TestRegistryResolve:
    def test_resolve_finds_production_version(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer", version="production")

        assert isinstance(pv, PromptVersion)
        assert pv.prompt_name == "rag_answer"
        assert pv.deployment_status == "production"

    def test_resolve_finds_hybrid_orchestrator(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("hybrid_orchestrator", version="production")

        assert pv.prompt_name == "hybrid_orchestrator"
        assert pv.version == "v1"

    def test_resolve_raises_for_unknown_name(self, registry: PromptRegistry) -> None:
        with pytest.raises(PromptNotFoundError):
            registry.resolve("nonexistent_prompt")

    def test_resolve_raises_for_wrong_status(self, registry: PromptRegistry) -> None:
        with pytest.raises(PromptNotFoundError):
            registry.resolve("rag_answer", version="canary")

    def test_resolve_returns_correct_parameters(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")

        assert pv.parameters.temperature == 0.0
        assert pv.parameters.max_tokens == 800
        assert pv.parameters.seed == 42
        assert pv.parameters.model == "gpt-4o"

    def test_resolve_prompt_text_is_non_empty(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")

        assert len(pv.prompt_text.strip()) > 0
        assert "{{masked_query}}" in pv.prompt_text

    def test_schema_path_is_set(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")

        assert pv.schema_path == "schemas/rag_output.schema.json"


# ---------------------------------------------------------------------------
# validate_output — schema validation
# ---------------------------------------------------------------------------

class TestValidateOutput:
    def test_validate_passes_valid_rag_output(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")
        valid_output = {
            "grounded": True,
            "answer": "The VAT rate is 9% [c-1].",
            "cited_chunks": ["c-1"],
            "confidence": 0.91,
            "insufficient_data_for": [],
        }

        registry.validate_output(pv, valid_output)  # must not raise

    def test_validate_raises_on_missing_required_field(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")
        bad_output = {
            "answer": "VAT is 9%.",
            "cited_chunks": [],
            "confidence": 0.5,
            "insufficient_data_for": [],
            # "grounded" missing
        }

        with pytest.raises(jsonschema.ValidationError):
            registry.validate_output(pv, bad_output)

    def test_validate_raises_on_confidence_out_of_range(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")
        bad_output = {
            "grounded": True,
            "answer": "VAT is 9%.",
            "cited_chunks": [],
            "confidence": 1.5,  # > 1.0
            "insufficient_data_for": [],
        }

        with pytest.raises(jsonschema.ValidationError):
            registry.validate_output(pv, bad_output)

    def test_validate_raises_on_additional_property(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")
        bad_output = {
            "grounded": False,
            "answer": None,
            "cited_chunks": [],
            "confidence": 0.0,
            "insufficient_data_for": [],
            "extra_field": "not allowed",
        }

        with pytest.raises(jsonschema.ValidationError):
            registry.validate_output(pv, bad_output)

    def test_validate_skips_when_schema_path_is_none(self, tmp_path: Path) -> None:
        yaml_body = (
            "id: no_schema_v1\n"
            "prompt_name: no_schema\n"
            "version: v1\n"
            "deployment_status: production\n"
            "parameters:\n"
            "  model: gpt-4o\n"
            "  temperature: 0.0\n"
            "  top_p: 1.0\n"
            "  max_tokens: 256\n"
            "prompt_text: |\n"
            "  SYSTEM: hello\n"
        )
        reg = _make_registry(tmp_path, yaml_body)
        pv = reg.resolve("no_schema", version="production")

        assert pv.schema_path is None
        reg.validate_output(pv, {"anything": True})  # must not raise

    def test_validate_passes_valid_hybrid_output(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("hybrid_orchestrator")
        valid_output = {
            "merged_answer": "The VAT rate is 9%.",
            "sql_contribution": "Confirmed from ERP ledger.",
            "rag_contribution": "Supported by tax circular §3.",
            "contradictions": [],
            "overall_confidence": 0.85,
            "cited_chunks": ["c-1"],
            "sql_tables_used": ["finance_vat"],
        }

        registry.validate_output(pv, valid_output)  # must not raise

    def test_validate_hybrid_raises_on_confidence_above_one(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("hybrid_orchestrator")
        bad_output = {
            "merged_answer": "answer",
            "sql_contribution": "sql",
            "rag_contribution": "rag",
            "contradictions": [],
            "overall_confidence": 2.0,
            "cited_chunks": [],
            "sql_tables_used": [],
        }

        with pytest.raises(jsonschema.ValidationError):
            registry.validate_output(pv, bad_output)


# ---------------------------------------------------------------------------
# YAML loading — data model completeness
# ---------------------------------------------------------------------------

class TestYamlLoading:
    def test_rag_answer_has_correct_id(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")
        assert pv.id == "rag_answer_v1"

    def test_hybrid_orchestrator_has_correct_id(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("hybrid_orchestrator")
        assert pv.id == "hybrid_orchestrator_v1"

    def test_rag_answer_schema_file_exists(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")
        schema_file = PROMPTS_DIR / pv.schema_path
        assert schema_file.exists()
        schema = json.loads(schema_file.read_text())
        assert schema.get("$schema") == "http://json-schema.org/draft-07/schema#"

    def test_hybrid_orchestrator_schema_file_exists(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("hybrid_orchestrator")
        schema_file = PROMPTS_DIR / pv.schema_path
        assert schema_file.exists()

    def test_metrics_defaults_to_none(self, registry: PromptRegistry) -> None:
        pv = registry.resolve("rag_answer")
        assert pv.metrics.classification_accuracy is None
        assert pv.metrics.sample_size == 0
