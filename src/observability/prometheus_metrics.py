"""
prometheus_metrics — All Prometheus counters and histograms for ERP Agentic RAG.

Metric naming follows Prometheus conventions: snake_case, _total suffix on counters
is added automatically by prometheus_client.

Organised by subsystem:
    request     — per-request latency and volume
    auth        — authentication failures
    rbac        — role-based access violations
    pii         — PII detection events
    sql         — 3-stage SQL pipeline (Sprints 1 & 4)
    worker      — Celery task dispatch/failure (Sprint 6)
    hybrid      — hybrid RAG+SQL agent (Sprint 7)
    llm         — LLM failure and circuit-breaker (Sprint 8)
    classifier  — query classifier accuracy (Sprint 9)
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Request / middleware — Sprint 1
# ---------------------------------------------------------------------------

REQUEST_LATENCY = Histogram(
    "erp_rag_request_latency_seconds",
    "End-to-end HTTP request latency in seconds",
    ["method", "endpoint", "status_code"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

REQUEST_COUNT = Counter(
    "erp_rag_requests_total",
    "Total HTTP requests received",
    ["method", "endpoint", "status_code"],
)

# ---------------------------------------------------------------------------
# Auth — Sprint 1
# ---------------------------------------------------------------------------

AUTH_FAILURE_RATE = Counter(
    "erp_rag_auth_failures_total",
    "Total authentication failures (expired, missing, tampered tokens)",
    ["reason"],
)

# ---------------------------------------------------------------------------
# RBAC — Sprint 1
# ---------------------------------------------------------------------------

RBAC_VIOLATION_RATE = Counter(
    "erp_rag_rbac_violations_total",
    "Total RBAC access violations (role forbidden from resource)",
    ["role", "resource"],
)

# ---------------------------------------------------------------------------
# PII — Sprint 1
# ---------------------------------------------------------------------------

PII_DETECTION_RATE = Counter(
    "erp_rag_pii_detections_total",
    "Total PII entities detected and masked",
    ["entity_type"],
)

# ---------------------------------------------------------------------------
# Middleware violations (generic, one per middleware layer) — Sprint 5
# ---------------------------------------------------------------------------

MIDDLEWARE_VIOLATIONS = Counter(
    "erp_rag_middleware_violations_total",
    "Total requests blocked or flagged by each middleware layer. "
    "Label values: auth | rate_limit_user | rate_limit_ip | rbac_module | pii",
    ["middleware"],
)

# ---------------------------------------------------------------------------
# SQL pipeline — Sprint 4
# ---------------------------------------------------------------------------

SQL_STAGE1_LATENCY = Histogram(
    "erp_rag_sql_stage1_latency_seconds",
    "Latency of Stage 1: natural language → SQL generation",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

SQL_STAGE2_ERRORS = Counter(
    "erp_rag_sql_stage2_errors_total",
    "Total Stage 2 SQL validation errors",
    ["reason"],
)

SQL_STAGE3_ROWS = Histogram(
    "erp_rag_sql_stage3_rows_returned",
    "Number of rows returned by Stage 3 SQL execution",
    buckets=(0, 1, 5, 10, 50, 100, 500, 1000),
)

SQL_PIPELINE_ERRORS = Counter(
    "erp_rag_sql_pipeline_errors_total",
    "Total SQL pipeline failures across all stages",
    ["stage"],
)

# ---------------------------------------------------------------------------
# Celery workers — Sprint 6
# ---------------------------------------------------------------------------

WORKER_TASKS_DISPATCHED = Counter(
    "erp_rag_worker_tasks_dispatched_total",
    "Total Celery tasks dispatched",
    ["task_name"],
)

WORKER_TASKS_FAILED = Counter(
    "erp_rag_worker_tasks_failed_total",
    "Total Celery task failures (after all retries exhausted)",
    ["task_name"],
)

WORKER_TASK_DURATION = Histogram(
    "erp_rag_worker_task_duration_seconds",
    "Celery task execution duration in seconds",
    ["task_name"],
    buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# ---------------------------------------------------------------------------
# Embed worker — Sprint 6
# ---------------------------------------------------------------------------

EMBED_TASKS_DISPATCHED = Counter(
    "erp_rag_embed_tasks_dispatched_total",
    "Total embed_asset Celery tasks dispatched",
    ["task_name"],
)

EMBED_TASKS_FAILED = Counter(
    "erp_rag_embed_tasks_failed_total",
    "Total embed_asset task failures (after all retries exhausted)",
    ["task_name"],
)

EMBED_TASK_DURATION = Histogram(
    "erp_rag_embed_task_duration_seconds",
    "embed_asset task execution duration in seconds",
    ["task_name"],
    buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# ---------------------------------------------------------------------------
# Hybrid agent — Sprint 7
# ---------------------------------------------------------------------------

HYBRID_SUCCESS_RATE = Counter(
    "erp_rag_hybrid_successes_total",
    "Total hybrid RAG+SQL queries that completed successfully",
)

HYBRID_LATENCY = Histogram(
    "erp_rag_hybrid_latency_seconds",
    "End-to-end latency of hybrid RAG+SQL queries",
    buckets=(0.5, 1.0, 2.0, 4.0, 8.0, 16.0),
)

HYBRID_PARTIAL_RATE = Counter(
    "erp_rag_hybrid_partial_total",
    "Hybrid queries that fell back to single-agent due to the other failing",
    ["fallback_mode"],  # "rag_only" | "sql_only"
)

# ---------------------------------------------------------------------------
# LLM health / degraded mode — Sprint 8
# ---------------------------------------------------------------------------

LLM_FAILURE_RATE = Counter(
    "erp_rag_llm_failures_total",
    "Total LLM call failures (connection errors, 5xx responses)",
    ["provider"],
)

CIRCUIT_BREAKER_STATE = Gauge(
    "erp_rag_circuit_breaker_open",
    "1 if the LLM circuit breaker is currently open, 0 if closed",
    ["provider"],
)

DEGRADED_MODE_ACTIVATIONS = Counter(
    "erp_rag_degraded_mode_activations_total",
    "Total times the system fell back to degraded mode",
)

# ---------------------------------------------------------------------------
# Per-request stage latency + token usage — Sprint 8 MetricsCollector
# ---------------------------------------------------------------------------

QUERY_STAGE_LATENCY_MS = Histogram(
    "erp_rag_query_latency_ms",
    "Per-pipeline-stage latency in milliseconds",
    ["stage"],
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)

TOKENS_USED = Counter(
    "erp_rag_tokens_used_total",
    "Total LLM tokens consumed",
    ["type"],  # "prompt" | "completion"
)

# ---------------------------------------------------------------------------
# Query classifier — Sprint 9
# ---------------------------------------------------------------------------

CLASSIFIER_BLOCKED_RATE = Counter(
    "erp_rag_classifier_blocked_total",
    "Total queries blocked by the query classifier (harmful / out-of-scope)",
    ["reason"],
)

CLASSIFIER_ACCURACY = Gauge(
    "erp_rag_classifier_accuracy",
    "Most recently measured query classifier accuracy (0.0–1.0)",
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # request
    "REQUEST_LATENCY",
    "REQUEST_COUNT",
    # auth
    "AUTH_FAILURE_RATE",
    # rbac
    "RBAC_VIOLATION_RATE",
    # pii
    "PII_DETECTION_RATE",
    # middleware
    "MIDDLEWARE_VIOLATIONS",
    # sql pipeline
    "SQL_STAGE1_LATENCY",
    "SQL_STAGE2_ERRORS",
    "SQL_STAGE3_ROWS",
    "SQL_PIPELINE_ERRORS",
    # workers — ingest
    "WORKER_TASKS_DISPATCHED",
    "WORKER_TASKS_FAILED",
    "WORKER_TASK_DURATION",
    # workers — embed
    "EMBED_TASKS_DISPATCHED",
    "EMBED_TASKS_FAILED",
    "EMBED_TASK_DURATION",
    # hybrid agent
    "HYBRID_SUCCESS_RATE",
    "HYBRID_LATENCY",
    "HYBRID_PARTIAL_RATE",
    # llm health
    "LLM_FAILURE_RATE",
    "CIRCUIT_BREAKER_STATE",
    "DEGRADED_MODE_ACTIVATIONS",
    # per-request accumulator
    "QUERY_STAGE_LATENCY_MS",
    "TOKENS_USED",
    # classifier
    "CLASSIFIER_BLOCKED_RATE",
    "CLASSIFIER_ACCURACY",
]
