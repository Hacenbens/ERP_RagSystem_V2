"""
Integration tests for the application entrypoint — Sprint 10.

src/main.py was untracked until this sprint: the single file defining the
middleware order, the router set and the lifespan container existed only on
one developer's machine and nothing verified it. These tests assert the
wiring the app actually boots with, so a change to it fails in CI rather
than at deploy time.

The container is stubbed. Building the real one reaches for whatever the
ambient environment happens to provide (Gemini, ngrok, Milvus), which is
exactly the dependency these tests must not have.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from src.infrastructure.di.container import DIContainer
from src.infrastructure.di.factory import build_query_chain
from src.infrastructure.auth.jwt_handler import JWTHandler
from src.infrastructure.auth.user_repository import InMemoryUserRepository
from src.middleware.public_paths import PUBLIC_PATHS
from src.use_cases.auth_user import AuthUseCase
from src.tests.fixtures.jwt_fixtures import make_jwt_handler


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Boot the real app object with a locally-built container."""
    import src.main as main

    def _stub_container() -> DIContainer:
        jwt_handler: JWTHandler = make_jwt_handler()
        user_repo = InMemoryUserRepository()
        container = DIContainer()
        container.register("jwt_handler", jwt_handler)
        container.register("user_repository", user_repo)
        container.register(
            "auth_use_case",
            AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler),
        )
        build_query_chain(container)
        container.validate()
        return container

    monkeypatch.setattr(main, "build_container", _stub_container)
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


class TestAppBoots:
    def test_lifespan_builds_and_validates_the_container(self, client):
        """Entering the TestClient context runs lifespan; a bad wiring raises."""
        assert client.app.state.container.is_bound("route_query_use_case")

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_openapi_schema_is_served(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        assert resp.json()["info"]["title"] == "ERP Agentic RAG"


class TestMountedRoutes:
    """Every router main.py includes must actually be reachable."""

    @pytest.mark.parametrize(
        "method,path",
        [
            ("POST", "/auth/register"),
            ("POST", "/auth/login"),
            ("GET", "/metrics"),
            ("GET", "/admin/jobs/some-id"),
            ("POST", "/api/v1/query"),
            ("POST", "/api/assets/upload"),
        ],
    )
    def test_route_is_registered(self, client, method, path):
        """A missing router shows up as 404; anything else means it is mounted."""
        routes = {
            (m, r.path)
            for r in client.app.routes
            for m in getattr(r, "methods", set())
        }
        assert any(
            m == method and _matches(path, tmpl) for m, tmpl in routes
        ), f"{method} {path} is not mounted"


def _matches(concrete: str, template: str) -> bool:
    """Compare a concrete path against a route template with {params}."""
    c, t = concrete.strip("/").split("/"), template.strip("/").split("/")
    if len(c) != len(t):
        return False
    return all(part.startswith("{") or part == got for got, part in zip(c, t))


class TestMiddlewareStack:
    def test_protected_route_requires_a_token(self, client):
        """AuthMiddleware is mounted and guarding non-public paths."""
        resp = client.post("/api/v1/query", json={"query": "anything"})
        assert resp.status_code == 401

    def test_no_public_path_returns_5xx(self, client):
        """Guards the Sprint 10 blocker at the level of the real app object."""
        for path in sorted(PUBLIC_PATHS):
            resp = client.get(path)
            assert resp.status_code < 500, (
                f"{path} returned {resp.status_code} — a middleware raised"
            )
