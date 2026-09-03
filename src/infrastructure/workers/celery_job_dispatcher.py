from __future__ import annotations

from typing import Any

from src.domain.ports.job_dispatcher_port import JobDispatcherPort


class CeleryJobDispatcher(JobDispatcherPort):
    """Dispatch ingestion and embedding jobs via Celery task .delay().

    In production the real Celery task callables are used.
    For unit tests pass a ``_task_factory`` dict mapping task names to
    mock callables so no broker connection is required.

    Example for tests::

        fake = MagicMock()
        fake.delay.return_value = MagicMock(id="test-id")
        dispatcher = CeleryJobDispatcher(_task_factory={
            "ingest_asset": fake,
            "embed_asset": fake,
        })
    """

    def __init__(self, _task_factory: dict[str, Any] | None = None) -> None:
        self._factory = _task_factory

    def dispatch_ingest(
        self,
        asset_id: str,
        tenant_id: str,
        chunk_strategy: str,
        storage_key: str,
    ) -> str:
        """Dispatch an ingest_asset Celery task and return its task id."""
        task = self._get_task("ingest_asset")
        result = task.delay(asset_id, tenant_id, chunk_strategy, storage_key)
        return result.id

    def dispatch_embed(self, asset_id: str, tenant_id: str, chunk_strategy: str) -> str:
        """Dispatch an embed_asset Celery task and return its task id."""
        task = self._get_task("embed_asset")
        result = task.delay(asset_id, tenant_id, chunk_strategy)
        return result.id

    def _get_task(self, name: str) -> Any:
        if self._factory is not None:
            return self._factory[name]
        if name == "ingest_asset":
            from src.infrastructure.workers.tasks.ingest_task import ingest_asset
            return ingest_asset
        if name == "embed_asset":
            from src.infrastructure.workers.tasks.embed_task import embed_asset
            return embed_asset
        raise KeyError(f"Unknown task: {name!r}")


__all__ = ["CeleryJobDispatcher"]
