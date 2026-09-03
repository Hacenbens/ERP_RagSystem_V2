"""
Unit tests — Sprint 7 Task 20
Covers: POST /api/assets/upload route
Includes both stub-based route tests and a real filesystem path-verification test.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.ports.asset_storage_port import AssetStoragePort
from src.domain.ports.job_dispatcher_port import JobDispatcherPort
from src.infrastructure.di.container import DIContainer
from src.infrastructure.storage.local_asset_storage import LocalAssetStorage
from src.routes.data import router


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubStorage(AssetStoragePort):
    """Records save_bytes calls without touching the filesystem."""

    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save_bytes(self, tenant_id: str, asset_id: str, filename: str, content: bytes) -> str:
        self.saved.append({"tenant_id": tenant_id, "asset_id": asset_id,
                           "filename": filename, "size": len(content)})
        return f"{tenant_id}/{asset_id}/{filename}"

    def read_bytes(self, tenant_id: str, storage_key: str) -> bytes:
        raise NotImplementedError

    def delete_bytes(self, tenant_id: str, storage_key: str) -> None:
        raise NotImplementedError


class _StubDispatcher(JobDispatcherPort):
    """Returns a deterministic job id without connecting to a broker."""

    JOB_ID = "job-test-123"

    def __init__(self) -> None:
        self.dispatched: list[dict] = []

    def dispatch_ingest(self, asset_id: str, tenant_id: str, chunk_strategy: str) -> str:
        self.dispatched.append({"asset_id": asset_id, "tenant_id": tenant_id,
                                "chunk_strategy": chunk_strategy})
        return self.JOB_ID

    def dispatch_embed(self, asset_id: str, tenant_id: str, chunk_strategy: str) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

TENANT_ID = "tenant-upload-test"


def _make_app(
    storage: AssetStoragePort | None = None,
    dispatcher: JobDispatcherPort | None = None,
) -> tuple[FastAPI, AssetStoragePort, _StubDispatcher]:
    _storage = storage or _StubStorage()
    _dispatcher = dispatcher or _StubDispatcher()

    container = DIContainer()
    container.register("asset_storage", _storage)
    container.register("job_dispatcher", _dispatcher)

    app = FastAPI()
    app.state.container = container
    app.include_router(router)

    @app.middleware("http")
    async def _inject_tenant(request, call_next):
        request.state.tenant_id = TENANT_ID
        return await call_next(request)

    return app, _storage, _dispatcher  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Tests — route behaviour (stub storage)
# ---------------------------------------------------------------------------

class TestUploadAsset:

    def _client(self, **kwargs) -> tuple[TestClient, AssetStoragePort, _StubDispatcher]:
        app, storage, dispatcher = _make_app(**kwargs)
        return TestClient(app, raise_server_exceptions=True), storage, dispatcher

    # --- Happy path --------------------------------------------------------

    def test_happy_path_returns_202(self):
        client, _, _ = self._client()
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
        )
        assert resp.status_code == 202

    def test_happy_path_response_has_asset_id(self):
        client, _, _ = self._client()
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("report.pdf", b"PDF content", "application/pdf")},
        )
        body = resp.json()
        assert "asset_id" in body
        assert len(body["asset_id"]) == 36  # uuid4 string length

    def test_happy_path_response_has_job_id(self):
        client, _, _ = self._client()
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("report.pdf", b"data", "application/pdf")},
        )
        assert resp.json()["job_id"] == _StubDispatcher.JOB_ID

    def test_happy_path_response_has_correct_filename(self):
        client, _, _ = self._client()
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("my_doc.txt", b"hello", "text/plain")},
        )
        assert resp.json()["filename"] == "my_doc.txt"

    def test_happy_path_response_has_correct_size_bytes(self):
        content = b"A" * 512
        client, _, _ = self._client()
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("big.bin", content, "application/octet-stream")},
        )
        assert resp.json()["size_bytes"] == 512

    def test_happy_path_default_chunk_strategy_is_sop(self):
        client, _, _ = self._client()
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("doc.txt", b"x", "text/plain")},
        )
        assert resp.json()["chunk_strategy"] == "sop"

    def test_happy_path_custom_chunk_strategy_propagated(self):
        client, _, _ = self._client()
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("doc.txt", b"x", "text/plain")},
            data={"chunk_strategy": "paragraph"},
        )
        assert resp.json()["chunk_strategy"] == "paragraph"

    def test_happy_path_storage_called_with_tenant_and_filename(self):
        client, storage, _ = self._client()
        client.post(
            "/api/assets/upload",
            files={"file": ("doc.txt", b"hello", "text/plain")},
        )
        assert isinstance(storage, _StubStorage)
        assert len(storage.saved) == 1
        assert storage.saved[0]["tenant_id"] == TENANT_ID
        assert storage.saved[0]["filename"] == "doc.txt"
        assert storage.saved[0]["size"] == 5

    def test_happy_path_dispatcher_called_with_correct_tenant(self):
        client, _, dispatcher = self._client()
        client.post(
            "/api/assets/upload",
            files={"file": ("f.txt", b"data", "text/plain")},
            data={"chunk_strategy": "sop"},
        )
        assert len(dispatcher.dispatched) == 1
        assert dispatcher.dispatched[0]["tenant_id"] == TENANT_ID
        assert dispatcher.dispatched[0]["chunk_strategy"] == "sop"

    def test_happy_path_dispatcher_asset_id_matches_response(self):
        client, _, dispatcher = self._client()
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("f.txt", b"data", "text/plain")},
        )
        assert dispatcher.dispatched[0]["asset_id"] == resp.json()["asset_id"]

    # --- Missing file field ------------------------------------------------

    def test_missing_file_returns_422(self):
        client, _, _ = self._client()
        resp = client.post("/api/assets/upload", data={"chunk_strategy": "sop"})
        assert resp.status_code == 422

    # --- Storage failure ---------------------------------------------------

    def test_storage_failure_returns_500(self):
        class _FailingStorage(AssetStoragePort):
            def save_bytes(self, tenant_id, asset_id, filename, content):
                raise RuntimeError("disk full")
            def read_bytes(self, tenant_id, storage_key):
                raise NotImplementedError
            def delete_bytes(self, tenant_id, storage_key):
                raise NotImplementedError

        client, _, _ = self._client(storage=_FailingStorage())
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("x.txt", b"y", "text/plain")},
        )
        assert resp.status_code == 500

    def test_storage_failure_does_not_dispatch_job(self):
        class _FailingStorage(AssetStoragePort):
            def save_bytes(self, tenant_id, asset_id, filename, content):
                raise RuntimeError("disk full")
            def read_bytes(self, tenant_id, storage_key):
                raise NotImplementedError
            def delete_bytes(self, tenant_id, storage_key):
                raise NotImplementedError

        dispatcher = _StubDispatcher()
        app, _, _ = _make_app(storage=_FailingStorage(), dispatcher=dispatcher)
        client = TestClient(app, raise_server_exceptions=False)
        client.post(
            "/api/assets/upload",
            files={"file": ("x.txt", b"y", "text/plain")},
        )
        assert len(dispatcher.dispatched) == 0


# ---------------------------------------------------------------------------
# Tests — real filesystem path verification
# ---------------------------------------------------------------------------

class TestUploadFileStoredAtCorrectPath:

    def test_file_saved_under_base_path_tenant_id_asset_id(self, tmp_path: Path):
        """Verify the file lands at {base_path}/{tenant_id}/{asset_id}/{filename}."""
        real_storage = LocalAssetStorage(base_path=str(tmp_path))
        app, _, _ = _make_app(storage=real_storage)
        client = TestClient(app, raise_server_exceptions=True)

        file_content = b"ERP document payload"
        resp = client.post(
            "/api/assets/upload",
            files={"file": ("invoice.pdf", file_content, "application/pdf")},
        )

        assert resp.status_code == 202
        asset_id = resp.json()["asset_id"]

        expected_path = tmp_path / TENANT_ID / asset_id / "invoice.pdf"
        assert expected_path.exists(), f"Expected file at {expected_path}"
        assert expected_path.read_bytes() == file_content

    def test_different_tenants_files_stored_in_separate_directories(self, tmp_path: Path):
        """Files for different tenants must not share the same directory."""
        real_storage = LocalAssetStorage(base_path=str(tmp_path))

        tenant_a, tenant_b = "tenant-a", "tenant-b"

        for tenant in (tenant_a, tenant_b):
            container = DIContainer()
            container.register("asset_storage", real_storage)
            container.register("job_dispatcher", _StubDispatcher())

            sub_app = FastAPI()
            sub_app.state.container = container
            sub_app.include_router(router)

            _tenant = tenant

            @sub_app.middleware("http")
            async def _inject(request, call_next, _t=_tenant):
                request.state.tenant_id = _t
                return await call_next(request)

            with TestClient(sub_app) as c:
                c.post(
                    "/api/assets/upload",
                    files={"file": ("data.txt", b"payload", "text/plain")},
                )

        assert (tmp_path / tenant_a).exists()
        assert (tmp_path / tenant_b).exists()
        assert (tmp_path / tenant_a) != (tmp_path / tenant_b)
