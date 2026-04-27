"""
Unit tests — DI Container and Factory (Sprint 3)
All tests use in-memory dependencies — no real DB or external services.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.di.container import DIContainer, MissingBindingError
from src.infrastructure.di.factory import build_container


# ---------------------------------------------------------------------------
# DIContainer — core behaviour
# ---------------------------------------------------------------------------

class TestDIContainerRegisterAndGet:
    def test_register_and_get_binding(self):
        container = DIContainer()
        impl = object()
        container.register("my_port", impl)
        assert container.get("my_port") is impl

    def test_get_unknown_port_raises_key_error(self):
        container = DIContainer()
        with pytest.raises(KeyError, match="my_missing_port"):
            container.get("my_missing_port")

    def test_register_overwrites_existing_binding(self):
        container = DIContainer()
        first = object()
        second = object()
        container.register("port", first)
        container.register("port", second)
        assert container.get("port") is second

    def test_is_bound_true(self):
        container = DIContainer()
        container.register("p", object())
        assert container.is_bound("p") is True

    def test_is_bound_false(self):
        container = DIContainer()
        assert container.is_bound("unregistered") is False

    def test_registered_ports_returns_all_keys(self):
        container = DIContainer()
        container.register("a", 1)
        container.register("b", 2)
        assert set(container.registered_ports()) == {"a", "b"}

    def test_repr_shows_bound_and_missing(self):
        container = DIContainer()
        container.register("user_repository", MagicMock())
        repr_str = repr(container)
        assert "user_repository" in repr_str


# ---------------------------------------------------------------------------
# DIContainer.validate() — the app startup gate
# ---------------------------------------------------------------------------

class TestDIContainerValidate:
    def test_validate_passes_when_all_required_bound(self):
        container = DIContainer()
        for port in DIContainer.REQUIRED_PORTS:
            container.register(port, MagicMock())
        container.validate()  # must not raise

    def test_validate_raises_on_single_missing_port(self):
        container = DIContainer()
        # Register all except the last required port
        for port in list(DIContainer.REQUIRED_PORTS)[:-1]:
            container.register(port, MagicMock())
        with pytest.raises(MissingBindingError) as exc_info:
            container.validate()
        assert DIContainer.REQUIRED_PORTS[-1] in str(exc_info.value)

    def test_validate_raises_listing_all_missing_ports(self):
        container = DIContainer()  # nothing registered
        with pytest.raises(MissingBindingError) as exc_info:
            container.validate()
        error_msg = str(exc_info.value)
        for port in DIContainer.REQUIRED_PORTS:
            assert port in error_msg

    def test_validate_empty_container_raises(self):
        container = DIContainer()
        with pytest.raises(MissingBindingError):
            container.validate()

    def test_missing_binding_error_is_runtime_error(self):
        assert issubclass(MissingBindingError, RuntimeError)


# ---------------------------------------------------------------------------
# DIFactory — build_container() wires everything correctly
# ---------------------------------------------------------------------------

class TestDIFactory:
    def test_build_container_returns_validated_container(self):
        container = build_container()
        assert isinstance(container, DIContainer)

    def test_build_container_has_all_required_ports(self):
        container = build_container()
        for port in DIContainer.REQUIRED_PORTS:
            assert container.is_bound(port), f"Required port '{port}' is not bound"

    def test_build_container_jwt_handler_is_functional(self):
        container = build_container()
        jwt_handler = container.get("jwt_handler")
        token = jwt_handler.issue(user_id="u1", role="ADMIN", tenant_id="t1")
        claims = jwt_handler.verify(token)
        assert claims.user_id == "u1"
        assert claims.role == "ADMIN"

    def test_build_container_auth_use_case_can_register_and_login(self):
        container = build_container()
        auth_use_case = container.get("auth_use_case")

        result = auth_use_case.register(
            username="factory_test_user",
            password="testpass123",
            role="MANAGER",
            tenant_id="acme",
        )
        assert result.username == "factory_test_user"
        assert result.role == "MANAGER"

        login = auth_use_case.login("factory_test_user", "testpass123")
        assert login.access_token
        assert login.role == "MANAGER"

    def test_build_container_user_repository_is_wired(self):
        container = build_container()
        repo = container.get("user_repository")
        repo.create(username="di_test_user", password="pass12345", role="VIEWER", tenant_id="t")
        record = repo.get_by_username("di_test_user")
        assert record.username == "di_test_user"

    def test_build_container_does_not_share_state_between_calls(self):
        """Each build_container() call returns an independent container."""
        c1 = build_container()
        c2 = build_container()
        repo1 = c1.get("user_repository")
        repo2 = c2.get("user_repository")
        assert repo1 is not repo2  # independent instances

    def test_select_vector_store_returns_in_memory_when_milvus_uri_absent(
        self, monkeypatch
    ):
        """Without MILVUS_URI, _select_vector_store() falls back to InMemoryVectorStore."""
        monkeypatch.delenv("MILVUS_URI", raising=False)
        from src.infrastructure.di.factory import _select_vector_store
        from src.infrastructure.vector_store.in_memory_vector_store import InMemoryVectorStore

        store = _select_vector_store()
        assert isinstance(store, InMemoryVectorStore)

    def test_select_vector_store_returns_milvus_when_uri_is_set(
        self, monkeypatch, tmp_path
    ):
        """With MILVUS_URI pointing to a .db file, _select_vector_store() returns MilvusVectorStore."""
        db_path = str(tmp_path / "factory_test.db")
        monkeypatch.setenv("MILVUS_URI", db_path)
        from src.infrastructure.di.factory import _select_vector_store
        from src.infrastructure.vector_store.milvus_vector_store import MilvusVectorStore

        store = _select_vector_store(dim=4)
        assert isinstance(store, MilvusVectorStore)


# ---------------------------------------------------------------------------
# AuthUseCase constructed with mocked dependencies
# ---------------------------------------------------------------------------

class TestAuthUseCaseWithMocks:
    def test_use_case_login_calls_repository_and_jwt(self):
        from src.use_cases.auth_user import AuthUseCase
        from src.infrastructure.auth.user_repository import UserRecord

        mock_repo = MagicMock()
        mock_repo.verify_password.return_value = UserRecord(
            user_id="mock-uid",
            username="mock-user",
            hashed_password="hashed",
            role="ANALYST",
            tenant_id="mock-tenant",
        )
        mock_jwt = MagicMock()
        mock_jwt.issue.return_value = "mock.jwt.token"

        use_case = AuthUseCase(user_repository=mock_repo, jwt_handler=mock_jwt)
        result = use_case.login("mock-user", "password")

        mock_repo.verify_password.assert_called_once_with("mock-user", "password")
        mock_jwt.issue.assert_called_once_with(
            user_id="mock-uid", role="ANALYST", tenant_id="mock-tenant"
        )
        assert result.access_token == "mock.jwt.token"
        assert result.role == "ANALYST"

    def test_use_case_register_calls_repository(self):
        from src.use_cases.auth_user import AuthUseCase
        from src.infrastructure.auth.user_repository import UserRecord

        mock_repo = MagicMock()
        mock_repo.create.return_value = UserRecord(
            user_id="new-uid",
            username="newuser",
            hashed_password="h",
            role="VIEWER",
            tenant_id="t",
        )
        use_case = AuthUseCase(user_repository=mock_repo, jwt_handler=MagicMock())
        result = use_case.register("newuser", "pass12345")

        mock_repo.create.assert_called_once_with(
            username="newuser", password="pass12345", role="VIEWER", tenant_id="default"
        )
        assert result.username == "newuser"

    def test_use_case_password_reset_stores_token(self):
        from src.use_cases.auth_user import AuthUseCase
        from src.infrastructure.auth.user_repository import UserRecord

        mock_repo = MagicMock()
        mock_repo.get_by_username.return_value = UserRecord(
            user_id="u1", username="user1", hashed_password="h", role="VIEWER", tenant_id="t"
        )
        use_case = AuthUseCase(user_repository=mock_repo, jwt_handler=MagicMock())
        result = use_case.request_password_reset("user1")

        mock_repo.save_reset_token.assert_called_once()
        assert result.reset_token  # non-empty
