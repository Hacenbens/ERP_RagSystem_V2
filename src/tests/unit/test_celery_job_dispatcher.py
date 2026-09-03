"""
Unit tests — CeleryJobDispatcher (Sprint 7 Task 17)
No real Celery broker — uses _task_factory injection.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


sys.path.insert(0, str(Path(__file__).parents[4]))

from src.infrastructure.workers.celery_job_dispatcher import CeleryJobDispatcher


ASSET_ID = "asset-xyz"
TENANT_ID = "tenant-abc"
STORAGE_KEY = "tenant-ferza/asset-abc-123/doc.txt"
STRATEGY = "sop"


def _make_dispatcher(task_id: str = "task-001") -> tuple[CeleryJobDispatcher, MagicMock, MagicMock]:
    ingest_mock = MagicMock()
    ingest_mock.delay.return_value = MagicMock(id=task_id)

    embed_mock = MagicMock()
    embed_mock.delay.return_value = MagicMock(id=task_id)

    dispatcher = CeleryJobDispatcher(_task_factory={
        "ingest_asset": ingest_mock,
        "embed_asset": embed_mock,
    })
    return dispatcher, ingest_mock, embed_mock


# ---------------------------------------------------------------------------
# dispatch_ingest
# ---------------------------------------------------------------------------

class TestDispatchIngest:
    def test_returns_task_id_string(self):
        dispatcher, _, _ = _make_dispatcher("ingest-id-123")
        result = dispatcher.dispatch_ingest(ASSET_ID, TENANT_ID, STRATEGY, STORAGE_KEY)
        assert result == "ingest-id-123"

    def test_calls_delay_with_correct_args(self):
        dispatcher, ingest_mock, _ = _make_dispatcher()
        dispatcher.dispatch_ingest(ASSET_ID, TENANT_ID, STRATEGY, STORAGE_KEY)
        ingest_mock.delay.assert_called_once_with(ASSET_ID, TENANT_ID, STRATEGY, STORAGE_KEY)

    def test_returns_string_not_async_result(self):
        dispatcher, _, _ = _make_dispatcher("abc")
        result = dispatcher.dispatch_ingest(ASSET_ID, TENANT_ID, STRATEGY, STORAGE_KEY)
        assert isinstance(result, str)

    def test_does_not_call_embed_task(self):
        dispatcher, _, embed_mock = _make_dispatcher()
        dispatcher.dispatch_ingest(ASSET_ID, TENANT_ID, STRATEGY, STORAGE_KEY)
        embed_mock.delay.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch_embed
# ---------------------------------------------------------------------------

class TestDispatchEmbed:
    def test_returns_task_id_string(self):
        dispatcher, _, _ = _make_dispatcher("embed-id-456")
        result = dispatcher.dispatch_embed(ASSET_ID, TENANT_ID, STRATEGY)
        assert result == "embed-id-456"

    def test_calls_delay_with_correct_args(self):
        dispatcher, _, embed_mock = _make_dispatcher()
        dispatcher.dispatch_embed(ASSET_ID, TENANT_ID, STRATEGY)
        embed_mock.delay.assert_called_once_with(ASSET_ID, TENANT_ID, STRATEGY)

    def test_returns_string_not_async_result(self):
        dispatcher, _, _ = _make_dispatcher("xyz")
        result = dispatcher.dispatch_embed(ASSET_ID, TENANT_ID, STRATEGY)
        assert isinstance(result, str)

    def test_does_not_call_ingest_task(self):
        dispatcher, ingest_mock, _ = _make_dispatcher()
        dispatcher.dispatch_embed(ASSET_ID, TENANT_ID, STRATEGY)
        ingest_mock.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Both tasks return independent ids
# ---------------------------------------------------------------------------

class TestTaskIdIndependence:
    def test_ingest_and_embed_can_return_different_ids(self):
        ingest_mock = MagicMock()
        ingest_mock.delay.return_value = MagicMock(id="ingest-001")
        embed_mock = MagicMock()
        embed_mock.delay.return_value = MagicMock(id="embed-002")

        dispatcher = CeleryJobDispatcher(_task_factory={
            "ingest_asset": ingest_mock,
            "embed_asset": embed_mock,
        })

        ingest_id = dispatcher.dispatch_ingest(ASSET_ID, TENANT_ID, STRATEGY, STORAGE_KEY)
        embed_id = dispatcher.dispatch_embed(ASSET_ID, TENANT_ID, STRATEGY)

        assert ingest_id == "ingest-001"
        assert embed_id == "embed-002"
        assert ingest_id != embed_id
