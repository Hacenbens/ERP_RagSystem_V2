"""
Unit tests — LocalAssetStorage (Sprint 7 Task 15)
All I/O uses a pytest tmp_path — no permanent filesystem state.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.storage.local_asset_storage import LocalAssetStorage


TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
ASSET_ID = "asset-001"
FILENAME = "report.pdf"
CONTENT = b"hello world bytes"


@pytest.fixture()
def storage(tmp_path) -> LocalAssetStorage:
    return LocalAssetStorage(base_path=str(tmp_path))


# ---------------------------------------------------------------------------
# save_bytes
# ---------------------------------------------------------------------------

class TestSaveBytes:
    def test_returns_storage_key(self, storage):
        key = storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, CONTENT)
        assert key == f"{TENANT_A}/{ASSET_ID}/{FILENAME}"

    def test_creates_file_on_disk(self, storage, tmp_path):
        storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, CONTENT)
        path = tmp_path / TENANT_A / ASSET_ID / FILENAME
        assert path.exists()
        assert path.read_bytes() == CONTENT

    def test_creates_directories_automatically(self, storage, tmp_path):
        storage.save_bytes(TENANT_A, "new-asset", "doc.txt", b"data")
        assert (tmp_path / TENANT_A / "new-asset" / "doc.txt").exists()

    def test_overwrites_on_second_save(self, storage):
        storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, b"v1")
        storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, b"v2")
        key = f"{TENANT_A}/{ASSET_ID}/{FILENAME}"
        assert storage.read_bytes(TENANT_A, key) == b"v2"


# ---------------------------------------------------------------------------
# read_bytes
# ---------------------------------------------------------------------------

class TestReadBytes:
    def test_round_trip(self, storage):
        key = storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, CONTENT)
        assert storage.read_bytes(TENANT_A, key) == CONTENT

    def test_missing_key_raises_file_not_found(self, storage):
        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT_A, f"{TENANT_A}/nonexistent/file.pdf")

    def test_cross_tenant_isolation_read(self, storage):
        key = storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, CONTENT)
        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT_B, key)


# ---------------------------------------------------------------------------
# delete_bytes
# ---------------------------------------------------------------------------

class TestDeleteBytes:
    def test_delete_removes_file(self, storage, tmp_path):
        key = storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, CONTENT)
        storage.delete_bytes(TENANT_A, key)
        assert not (tmp_path / TENANT_A / ASSET_ID / FILENAME).exists()

    def test_delete_then_read_raises(self, storage):
        key = storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, CONTENT)
        storage.delete_bytes(TENANT_A, key)
        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT_A, key)

    def test_delete_missing_raises_file_not_found(self, storage):
        with pytest.raises(FileNotFoundError):
            storage.delete_bytes(TENANT_A, f"{TENANT_A}/ghost/file.pdf")

    def test_cross_tenant_isolation_delete(self, storage):
        key = storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, CONTENT)
        with pytest.raises(FileNotFoundError):
            storage.delete_bytes(TENANT_B, key)


# ---------------------------------------------------------------------------
# Full round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_save_read_delete_read(self, storage):
        key = storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, CONTENT)
        assert storage.read_bytes(TENANT_A, key) == CONTENT
        storage.delete_bytes(TENANT_A, key)
        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT_A, key)

    def test_two_tenants_same_asset_id_are_isolated(self, storage):
        key_a = storage.save_bytes(TENANT_A, ASSET_ID, FILENAME, b"tenant-a-data")
        key_b = storage.save_bytes(TENANT_B, ASSET_ID, FILENAME, b"tenant-b-data")
        assert storage.read_bytes(TENANT_A, key_a) == b"tenant-a-data"
        assert storage.read_bytes(TENANT_B, key_b) == b"tenant-b-data"
        with pytest.raises(FileNotFoundError):
            storage.read_bytes(TENANT_A, key_b)
