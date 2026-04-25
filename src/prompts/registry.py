"""Prompt versioning registry.

Loads PromptVersion objects from YAML files under *prompts_dir/versions/*.
Output dicts are optionally validated against JSON Schema draft-07 files
stored under *prompts_dir/schemas/*.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import jsonschema
import yaml

DeploymentStatus = Literal["shadow", "canary", "production", "deprecated"]


@dataclass
class PromptParameters:
    model: str
    temperature: float
    top_p: float
    max_tokens: int
    seed: int = 42


@dataclass
class PromptMetrics:
    classification_accuracy: float | None = None
    hallucination_rate: float | None = None
    grounding_score: float | None = None
    latency_p95_ms: float | None = None
    sample_size: int = 0
    evaluated_at: str | None = None


@dataclass
class PromptVersion:
    id: str
    prompt_name: str
    version: str
    prompt_text: str
    parameters: PromptParameters
    metrics: PromptMetrics = field(default_factory=PromptMetrics)
    deployment_status: DeploymentStatus = "shadow"
    schema_path: str | None = None
    created_at: str = ""
    changelog: str = ""


class PromptNotFoundError(KeyError):
    """Raised when no prompt matches the requested name + deployment status."""


class PromptRegistry:
    """Load and resolve versioned prompts from a directory of YAML files.

    Directory layout expected::

        <prompts_dir>/
            versions/
                rag_answer_v1.yaml
                hybrid_orchestrator_v1.yaml
                ...
            schemas/
                rag_output.schema.json
                hybrid_output.schema.json
                ...
    """

    def __init__(self, prompts_dir: str | Path) -> None:
        self._dir = Path(prompts_dir)
        self._versions: list[PromptVersion] = []
        self._load_all()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, name: str, version: DeploymentStatus = "production") -> PromptVersion:
        """Return the PromptVersion for *name* with the given *deployment_status*.

        Raises PromptNotFoundError when no match is found.
        """
        matches = [
            pv
            for pv in self._versions
            if pv.prompt_name == name and pv.deployment_status == version
        ]
        if not matches:
            raise PromptNotFoundError(
                f"No prompt '{name}' with deployment_status='{version}'"
            )
        return matches[0]

    def validate_output(self, pv: PromptVersion, output: dict) -> None:
        """Validate *output* against the JSON Schema referenced by *pv*.

        No-op when ``pv.schema_path`` is None.
        Raises ``jsonschema.ValidationError`` on schema mismatch.
        """
        if pv.schema_path is None:
            return
        schema_file = self._dir / pv.schema_path
        schema = json.loads(schema_file.read_text())
        jsonschema.validate(instance=output, schema=schema)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        versions_dir = self._dir / "versions"
        if not versions_dir.is_dir():
            return
        for path in sorted(versions_dir.glob("*.yaml")):
            self._versions.append(self._load_file(path))

    def _load_file(self, path: Path) -> PromptVersion:
        raw = yaml.safe_load(path.read_text())
        params_raw = raw.get("parameters", {})
        metrics_raw = raw.get("metrics", {})
        return PromptVersion(
            id=raw["id"],
            prompt_name=raw["prompt_name"],
            version=raw["version"],
            prompt_text=raw["prompt_text"],
            parameters=PromptParameters(
                model=params_raw.get("model", "gpt-4o"),
                temperature=float(params_raw.get("temperature", 0.0)),
                top_p=float(params_raw.get("top_p", 1.0)),
                max_tokens=int(params_raw.get("max_tokens", 512)),
                seed=int(params_raw.get("seed", 42)),
            ),
            metrics=PromptMetrics(
                classification_accuracy=metrics_raw.get("classification_accuracy"),
                hallucination_rate=metrics_raw.get("hallucination_rate"),
                grounding_score=metrics_raw.get("grounding_score"),
                latency_p95_ms=metrics_raw.get("latency_p95_ms"),
                sample_size=int(metrics_raw.get("sample_size", 0)),
                evaluated_at=metrics_raw.get("evaluated_at"),
            ),
            deployment_status=raw.get("deployment_status", "shadow"),
            schema_path=raw.get("schema_path"),
            created_at=str(raw.get("created_at", "")),
            changelog=str(raw.get("changelog", "")),
        )
