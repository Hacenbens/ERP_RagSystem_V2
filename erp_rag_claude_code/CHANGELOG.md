# CHANGELOG

All notable changes to the ERP Agentic RAG system are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

Each sprint gets one entry. Entries are added by the Committer agent at sprint close.

---

## [sprint-2-done] — 2026-04-08

### Added
- feat(evaluation): `evaluation/__init__.py` — module scaffold
- feat(evaluation): `evaluation/benchmarks/sql_benchmark.py` — 20 ERP NL→SQL test cases; CI-compatible (exit 0/1); offline stub + real pipeline hook; reports success_rate vs `SQL_SUCCESS_MIN` threshold
- feat(evaluation): `evaluation/benchmarks/data/sql_test_cases.json` — 20 committed test cases covering sales, inventory, HR, finance, logistics, tax domains; all require `tenant_id` filter
- feat(evaluation): `evaluation/metrics/hallucination_scorer.py` — LLM-as-judge scorer; returns `grounding_score` in [0.0, 1.0]; heuristic fallback for offline/test use; `is_acceptable` flag against `HALLUCINATION_MAX`
- feat(evaluation): `evaluation/benchmarks/rag_benchmark.py` — 15 retrieval test cases; precision@5 reporting; CI-compatible exit codes
- feat(evaluation): `evaluation/benchmarks/data/rag_test_cases.json` — 15 committed retrieval cases covering SOPs, BPMN processes, tax circulars
- feat(config): `helpers/config.py` — central threshold config (`SQL_SUCCESS_MIN=0.95`, `HALLUCINATION_MAX=0.05`, `RAG_PRECISION_MIN=0.70`); all overridable via env vars
- feat(ci): `.github/workflows/ci.yml` — lint (ruff) + type check (mypy) + unit tests (coverage ≥80%) + SQL benchmark gate + RAG benchmark gate on every PR to develop
- test(evaluation): `src/tests/unit/test_evaluation.py` — 51 unit tests covering all benchmark and scorer components; all green

### Definition of Done — Sprint 2 ✓
- `sql_benchmark.py` runs 20 queries — reports pass/fail per query and overall `success_rate`
- CI fails PR if `sql_success_rate < 0.95` or `hallucination_rate > 0.05`
- `hallucination_scorer.py` returns `grounding_score` between 0.0 and 1.0 for any answer/context pair
- `rag_benchmark.py` runs 15 retrieval cases and reports precision@5
- All benchmark scripts exit with code 0 on pass, 1 on fail (CI-compatible)
- Sprint tag `sprint-2-done` pushed, CHANGELOG updated

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
