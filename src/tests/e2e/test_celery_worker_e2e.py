"""
E2E tests — Sprint 6 Task 1 (Celery worker + real broker)

Requires: Redis on CELERY_BROKER_URL, MongoDB on MONGODB_URI.
Run with:  pytest src/tests/e2e/ -m e2e --timeout=60

These tests are SKIPPED automatically when the broker is unreachable,
so they never block the unit/integration suite.
"""
from __future__ import annotations

import os

import pytest

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "")
MONGO_URI = os.environ.get("MONGODB_URI", "")

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def require_broker():
    if not BROKER_URL:
        pytest.skip("CELERY_BROKER_URL not set — skipping e2e broker tests")
    if not MONGO_URI:
        pytest.skip("MONGODB_URI not set — skipping e2e broker tests")


class TestIngestAssetE2E:
    """Full round-trip: task dispatched to real Redis broker, result fetched."""

    def test_ingest_asset_dispatched_and_completed(self, require_broker):
        from src.workers.tasks.ingest_task import ingest_asset

        result = ingest_asset.apply_async(
            args=["e2e-asset-001", "tenant-e2e", "sop"],
            expires=30,
        )
        outcome = result.get(timeout=20, propagate=True)
        assert outcome["status"] in ("success", "skipped")

    def test_dead_letter_written_to_mongo_on_permanent_failure(self, require_broker):
        """Dispatches a task that will fail all retries and checks MongoDB dead-letter."""
        import pymongo

        from src.workers.tasks.ingest_task import ingest_asset

        # Use an asset_id that triggers failure in the stub chunker
        result = ingest_asset.apply_async(
            args=["e2e-fail-asset", "tenant-e2e", "unknown_strategy"],
            expires=120,
        )
        with pytest.raises(Exception):
            result.get(timeout=60, propagate=True)

        client = pymongo.MongoClient(MONGO_URI)
        count = client["erp_rag"]["failed_tasks"].count_documents(
            {"asset_id": "e2e-fail-asset", "tenant_id": "tenant-e2e"}
        )
        assert count >= 1
