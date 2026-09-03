"""
Deployment configuration — Sprint 11 (G2·1, G2·2, G2·3 partial).

The compose stack could not build: it referenced docker/Dockerfile twice and
that file did not exist. Even with one, it pointed at three things that had
moved or been replaced:

  - the worker command targeted src.workers.celery_app, a path that moved in
    Sprint 6
  - MILVUS_HOST / MILVUS_PORT were set while the code reads a URI
  - OPENAI_API_KEY was passed while the code uses Gemini and the ngrok model
    server, neither of which appeared anywhere

None of that is exercised by importing Python, so it drifted silently for
three sprints. These are static assertions over the checked-in files: cheap,
run in CI, and they fail the moment configuration and code disagree again.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO / "docker" / "docker-compose.yaml"
DOCKERFILE_PATH = REPO / "docker" / "Dockerfile"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text())


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE_PATH.read_text()


class TestTheImageExists:
    def test_dockerfile_is_present(self):
        """Compose referenced it twice; it was never written."""
        assert DOCKERFILE_PATH.is_file()

    @pytest.mark.parametrize("service", ["app", "worker"])
    def test_service_build_points_at_the_real_file(self, compose, service):
        build = compose["services"][service]["build"]
        referenced = REPO / "docker" / Path(build["dockerfile"]).name

        assert referenced.is_file()

    def test_dockerignore_excludes_env(self):
        """A baked-in .env would ship real API keys inside the image layer."""
        ignored = (REPO / ".dockerignore").read_text().splitlines()

        assert ".env" in ignored

    def test_image_runs_unprivileged(self, dockerfile):
        assert "USER erprag" in dockerfile

    def test_output_is_unbuffered(self, dockerfile):
        """Buffered stdout means `docker logs` shows nothing until exit."""
        assert "PYTHONUNBUFFERED=1" in dockerfile


class TestWorkerCommand:
    def test_celery_app_path_is_the_one_that_exists(self, compose):
        """src.workers.celery_app moved to src.infrastructure.workers in Sprint 6."""
        command = compose["services"]["worker"]["command"]

        assert "src.infrastructure.workers.celery_app" in command
        assert "-A src.workers.celery_app" not in command

    def test_the_module_really_is_importable(self):
        """Pins the assertion above to reality rather than to a string."""
        import importlib

        assert importlib.import_module("src.infrastructure.workers.celery_app")


def _env_of(compose: dict, service: str) -> dict:
    env = compose["services"][service].get("environment", {})
    if isinstance(env, list):
        return dict(item.split("=", 1) for item in env)
    return env


class TestEnvironmentMatchesTheCode:
    @pytest.mark.parametrize("service", ["app", "worker"])
    def test_milvus_uses_the_uri_variable(self, compose, service):
        env = _env_of(compose, service)

        assert "MILVUS_DB_URI" in env
        assert "MILVUS_HOST" not in env and "MILVUS_PORT" not in env

    @pytest.mark.parametrize("service", ["app", "worker"])
    def test_milvus_uri_is_an_http_address(self, compose, service):
        """pymilvus rejects a file path against a server URI."""
        assert _env_of(compose, service)["MILVUS_DB_URI"].startswith("http")

    @pytest.mark.parametrize("service", ["app", "worker"])
    def test_the_dead_openai_key_is_gone(self, compose, service):
        """Gemini replaced OpenAI in Sprint 8; compose never noticed."""
        assert "OPENAI_API_KEY" not in _env_of(compose, service)

    @pytest.mark.parametrize("service", ["app", "worker"])
    def test_secrets_come_from_env_file_not_empty_substitutions(
        self, compose, service
    ):
        """Compose resolves ${VAR} against docker/.env, not the repo root.

        Listing GEMINI_API_KEY here as ${GEMINI_API_KEY} would resolve to ""
        and override the real value env_file supplies.
        """
        env = _env_of(compose, service)
        env_files = compose["services"][service]["env_file"]

        assert any("../.env" in str(entry) for entry in env_files)
        for secret in ("GEMINI_API_KEY", "NGROK_API_KEY", "ERP_PG_PASSWORD"):
            assert secret not in env

    @pytest.mark.parametrize("service", ["app", "worker"])
    def test_env_file_is_optional(self, compose, service):
        """A fresh clone with no .env must still start."""
        entry = compose["services"][service]["env_file"][0]

        assert entry["required"] is False


class TestUploadsAreShared:
    """G2·3 — the worker must read what the API wrote."""

    @pytest.mark.parametrize("service", ["app", "worker"])
    def test_both_mount_the_asset_volume(self, compose, service):
        mounts = compose["services"][service].get("volumes", [])

        assert any("asset_data:" in m for m in mounts), (
            f"{service} has no shared asset volume — the worker would look on "
            "its own disk and find nothing, reproducing the B-4 failure at the "
            "container boundary"
        )

    def test_the_volume_is_declared(self, compose):
        assert "asset_data" in compose["volumes"]

    @pytest.mark.parametrize("service", ["app", "worker"])
    def test_the_mount_path_matches_the_configured_path(self, compose, service):
        env = _env_of(compose, service)
        mounts = compose["services"][service]["volumes"]

        assert any(m.endswith(env["ASSET_STORAGE_PATH"]) for m in mounts)
