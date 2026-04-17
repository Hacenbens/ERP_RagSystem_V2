# End-to-End Tests (`tests/e2e/`)

Tests in this folder require **real infrastructure** (Redis broker, MongoDB, Milvus).
They are excluded from the standard `pytest` run and executed only in CI via Docker Compose.

## Infrastructure required

| Service   | Role                          | Docker image           |
|-----------|-------------------------------|------------------------|
| Redis     | Celery broker + result backend | `redis:7-alpine`       |
| MongoDB   | Dead-letter + idempotency store | `mongo:7`             |
| Milvus    | Vector store (Sprint 7+)       | `milvusdb/milvus`     |

## Running locally

```bash
# Start infrastructure
docker compose -f docker/compose.e2e.yml up -d

# Run e2e suite only
pytest src/tests/e2e/ -m e2e --timeout=60

# Tear down
docker compose -f docker/compose.e2e.yml down
```

## Pytest marker

All tests in this folder must be decorated with `@pytest.mark.e2e`.
The marker is registered in `conftest.py` and excluded from the default run:

```ini
# pyproject.toml / pytest.ini
addopts = -m "not e2e"
```

## What belongs here (by sprint)

| Sprint | Test file                          | Coverage                                  |
|--------|------------------------------------|-------------------------------------------|
| 6      | `test_celery_worker_e2e.py`        | ingest_asset dispatched to real broker, dead-letter in MongoDB |
| 7      | `test_hybrid_agent_e2e.py`         | RAG + SQL parallel query against real Milvus + PG |
| 8      | `test_degraded_mode_e2e.py`        | Model fallback when primary LLM unavailable |
