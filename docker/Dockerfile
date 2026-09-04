# syntax=docker/dockerfile:1
#
# ERP Agentic RAG — application image.
#
# One image serves both roles; docker-compose overrides the command for the
# Celery worker. They share a codebase and a dependency set, so two images
# would only add a way for them to drift.
#
# Build from the repository root:
#   docker build -f docker/Dockerfile -t erp-rag:dev .

FROM python:3.13-slim AS base

# - PYTHONDONTWRITEBYTECODE: the layer is read-only at runtime anyway
# - PYTHONUNBUFFERED: without it the structured JSON logs sit in a buffer and
#   `docker logs` shows nothing until the process exits
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# curl is here for the compose healthcheck, which shells out to it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies in their own layer, before the source copy, so editing code does
# not reinstall the tree (unstructured and pymilvus dominate the build).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY helpers/ ./helpers/
COPY evaluation/ ./evaluation/

# Run unprivileged. The asset directory is created here because the volume
# mount inherits root ownership otherwise and uploads fail with EACCES.
RUN useradd --create-home --uid 10001 erprag \
    && mkdir -p /var/lib/erp_rag/assets \
    && chown -R erprag:erprag /app /var/lib/erp_rag
USER erprag

ENV ASSET_STORAGE_PATH=/var/lib/erp_rag/assets

EXPOSE 8000

# Overridden by the worker service in docker-compose.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
