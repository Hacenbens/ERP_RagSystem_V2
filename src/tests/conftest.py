"""
Shared pytest fixtures for integration tests — Sprint 3.
Provides a fully wired FastAPI TestClient with:
  - AuthMiddleware (real RS256)
  - RBACMiddleware
  - Auth routes (/auth/*)
  - A protected route (/api/erp/query stub)
  - DI container with in-memory user store and test JWT handler
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient


from src.infrastructure.auth.jwt_handler import JWTHandler
from src.infrastructure.auth.user_repository import InMemoryUserRepository
from src.infrastructure.di.container import DIContainer
from src.infrastructure.di.factory import build_query_chain
from src.middleware.AuthMiddleware import AuthMiddleware
from src.middleware.RBACMiddleware import RBACMiddleware
from src.routes.auth import router as auth_router
from src.use_cases.auth_user import AuthUseCase
from src.tests.fixtures.jwt_fixtures import make_jwt_handler


def build_test_app(jwt_handler: JWTHandler | None = None) -> tuple[FastAPI, DIContainer]:
    """Build a minimal FastAPI app wired for integration testing."""
    if jwt_handler is None:
        jwt_handler = make_jwt_handler()

    user_repo = InMemoryUserRepository()
    auth_use_case = AuthUseCase(user_repository=user_repo, jwt_handler=jwt_handler)

    container = DIContainer()
    container.register("jwt_handler", jwt_handler)
    container.register("user_repository", user_repo)
    container.register("auth_use_case", auth_use_case)

    # Wire query chain so container.validate() passes (added Sprint 7 Task 10)
    build_query_chain(container)
    container.validate()

    app = FastAPI()
    app.state.container = container

    # Middleware stack (order matters — outermost added last with add_middleware)
    app.add_middleware(RBACMiddleware)
    app.add_middleware(AuthMiddleware)

    # Routes
    app.include_router(auth_router)

    # Protected stub route for RBAC / auth tests
    @app.get("/api/erp/query")
    async def erp_query(request: Request):
        return {
            "result": "ok",
            "user_id": getattr(request.state, "user_id", None),
            "role": getattr(request.state, "role", None),
        }

    # Admin-only route
    @app.get("/admin/status")
    async def admin_status(request: Request):
        return {"status": "healthy", "role": getattr(request.state, "role", None)}

    # Health endpoint (public)
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app, container


# ---------------------------------------------------------------------------
# Environment isolation
# ---------------------------------------------------------------------------

# Variables that steer what the DI factory selects. langsmith calls
# load_dotenv() when it is imported, and langchain_text_splitters pulls it in,
# so the developer's real .env reaches the test process whether or not any
# project code asks for it. Once that .env held real values, tests asserting
# in-memory defaults started failing against MongoDB, PostgreSQL and the
# operator's JWT keys — the suite was reading the machine it ran on.
_DI_STEERING_VARS = (
    "MONGODB_URI",
    "MILVUS_DB_URI",
    "ERP_PG_PASSWORD",
    "ERP_PG_DSN",
    "NGROK_BASE_URL",
    "GEMINI_API_KEY",
    "VLLM_BASE_URL",
    "VLLM_MODEL",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "JWT_PRIVATE_KEY_PEM",
    "JWT_PUBLIC_KEY_PEM",
    "JWT_PRIVATE_KEY_PATH",
    "JWT_PUBLIC_KEY_PATH",
)


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test against the in-memory defaults, whatever .env holds.

    A test that wants a real service sets its own variable afterwards — this
    runs first, so monkeypatch.setenv in a test still wins. Deliberately does
    not clear the *_TEST_* variables that gate the opt-in integration suites
    (MINIO_TEST_ENDPOINT, ERP_PG_TEST_DSN); those name a fixture explicitly
    rather than steering production selection.
    """
    for name in _DI_STEERING_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def jwt_handler() -> JWTHandler:
    return make_jwt_handler()


@pytest.fixture()
def app(jwt_handler):
    app, _ = build_test_app(jwt_handler=jwt_handler)
    return app


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def registered_user(client) -> dict:
    """Register a VIEWER user and return their credentials."""
    resp = client.post("/auth/register", json={
        "username": "testuser",
        "password": "testpass123",
        "role": "REPORTING_ANALYST",
        "tenant_id": "tenant-abc",
    })
    assert resp.status_code == 201
    return {"username": "testuser", "password": "testpass123"}


@pytest.fixture()
def auth_token(client, registered_user, jwt_handler) -> str:
    """Log in and return a valid JWT."""
    resp = client.post("/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]
