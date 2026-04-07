# CHANGELOG

All notable changes to the ERP Agentic RAG system are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

Each sprint gets one entry. Entries are added by the Committer agent at sprint close.

---

## [sprint-1-done] — 2026-04-08

### Added
- feat(observability): `src/observability/__init__.py` — module scaffold with `__version__`, `get_logger()` lazy import
- feat(observability): `src/observability/prometheus_metrics.py` — 19 Prometheus metrics across 7 subsystems (auth, rbac, pii, request, sql-pipeline, workers, hybrid, llm, classifier)
- feat(observability): `src/observability/structured_logger.py` — JSON structured logger with `trace_id`/`user_id` propagation via `contextvars`; `set_trace_context()` API
- feat(middleware): `src/middleware/LoggingMiddleware.py` — outermost middleware; emits JSON log per request with `trace_id`, `user_id`, `latency_ms`, `status_code`; increments `REQUEST_LATENCY` histogram
- feat(middleware): `src/middleware/AuthMiddleware.py` — Sprint 1 stub; missing/empty Bearer token → 401; increments `AUTH_FAILURE_RATE`
- feat(middleware): `src/middleware/RateLimitMiddleware.py` — Sprint 1 stub; sliding-window counter; logs violations without blocking (Sprint 5 gate)
- feat(middleware): `src/middleware/RBACMiddleware.py` — Sprint 1 stub; non-ADMIN on `/admin/*` → 403; `ModuleAccessGuard` extension point marked for Sprint 5
- feat(middleware): `src/middleware/PIIMaskingMiddleware.py` — detects email, DZ phone (+213), NID (18-digit), tax ID (15-digit); stores masked query in `request.state`; increments `PII_DETECTION_RATE`
- feat(observability): `src/routes/admin.py` — `GET /metrics` returns valid Prometheus text format via `generate_latest()`; public route (no auth); `GET /admin/jobs/{id}` Sprint 6 stub
- chore(ci): `docker/docker-compose.yaml` — 8-service local stack (app, worker, mongodb, etcd, milvus, minio, redis, prometheus)
- chore(ci): `docker/prometheus/prometheus.yml` — scrapes `app:8000/metrics` every 15s

### Fixed
- fix(auth): `AuthMiddleware` now rejects `"Bearer "` (empty token after prefix) with 401

### Tested
- test(observability): 69 unit tests — **96% coverage** on `src/observability/` + `src/middleware/` + `src/routes/` (target: ≥ 80%)
- Lint: **ruff — 0 errors**
- Type check: **mypy — 0 errors**

---

## [Unreleased]

_Work in progress — not yet tagged_

---

<!-- SPRINT ENTRIES WILL BE ADDED BELOW BY THE COMMITTER AGENT -->
<!-- Format:
## [sprint-N-done] — YYYY-MM-DD
### Added
- feat(scope): description
### Fixed
- fix(scope): description
### Tested
- test(scope): benchmark results
-->

---

## Project Baseline — 2026-04-08

### Context
- Architecture mapping completed (ERP_RAG_Architecture_Mapping.docx)
- Sprint plan defined (ERP_RAG_Sprint_Plan_GitStrategy.docx)
- Claude Code project initialized with 4 sub-agents
- 10-sprint plan: observability → evaluation → DI → SQL → middleware →
  workers → hybrid → model-selection → query-intelligence → hardening

### Known Gaps at Baseline
- `observability/` module: not yet created (Sprint 1)
- `evaluation/` module: not yet created (Sprint 2)
- SQL benchmark: not yet implemented (Sprint 2)
- Hybrid agent: not yet implemented (Sprint 7)
- Prometheus metrics: not yet exported (Sprint 1)
