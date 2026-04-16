# CHANGELOG

All notable changes to the ERP Agentic RAG system are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

Each sprint gets one entry. Entries are added by the Committer agent at sprint close.

---

## [sprint-5-done] — 2026-04-16

### Added
- feat(middleware): `src/middleware/RateLimitMiddleware.py` — enforce 429 rate limiting: 60 req/min per user, 200 req/min per IP; per-instance sliding-window counters
- feat(middleware): `src/infrastructure/erp/erp_rbac_policy.py` — `MODULE_ACCESS_MATRIX` + policy functions; maps ERP modules to allowed roles
- feat(domain): `src/domain/enums.py` — canonical enum layer: `UserRole`, `QueryIntent`, `ChunkStrategy`, `ErpModule`
- feat(middleware): `src/middleware/RBACMiddleware.py` — module guard upgrade integrating `MODULE_ACCESS_MATRIX`; role migration to canonical enums
- feat(observability): `MIDDLEWARE_VIOLATIONS` Prometheus counter wired into `AuthMiddleware`, `RateLimitMiddleware`, `RBACMiddleware`, `PIIMaskingMiddleware`

### Fixed
- fix(middleware): move `RateLimitMiddleware` counters from module globals to per-instance — prevents counter bleed across test cases
- fix(middleware): add digit lookarounds to `phone_dz` regex pattern — prevent false positives inside 18-digit NID sequences

### Tested
- test(middleware): `src/tests/integration/test_rate_limit.py` — per-user throttle (60/min), per-IP throttle (200/min), burst handling; 429 gate verified
- test(middleware): `src/tests/integration/test_module_guard.py` — SQL table filtering per ERP module; ANALYST blocked from finance_schema (403)
- test(middleware): `src/tests/unit/test_pii_masking.py` — 30-query fixture; ≥98% recall gate on email, phone (DZ), NID (18-digit), tax ID (15-digit)
- test(performance): `src/tests/performance/test_middleware_latency.py` — full 5-layer stack overhead < 20ms p99 confirmed
- test(middleware): `src/tests/integration/test_middleware_violations.py` — `MIDDLEWARE_VIOLATIONS` counter increments verified per middleware
- test(middleware): `src/tests/integration/test_middleware_order.py` — auth rejection never reaches SQL pipeline; short-circuit ordering verified
- docs(middleware): `ARCHITECTURE.md` — RBACMiddleware + `erp_rbac_policy.py` decision matrix documented

### Definition of Done — Sprint 5 ✓
- Rate limiting: 60 req/min per user, 200 req/min per IP — verified by integration test
- ANALYST role cannot query finance_schema — ModuleGuard returns 403 — verified by test
- PII masking ≥98% recall on email, DZ phone, NID (18-digit), tax ID (15-digit)
- Full 5-layer middleware stack adds < 20ms overhead (p99) — verified by performance test
- `MIDDLEWARE_VIOLATIONS` counter visible in Prometheus for all 4 middleware layers
- 626 tests total — all green
- Sprint tag `sprint-5-done` pushed, CHANGELOG updated

---

## [sprint-4-done] — 2026-04-09

### Added
- feat(sql): `src/infrastructure/erp/query_generator.py` — Stage 1: NL→SQL with offline fallback + OpenAI hook; `SQL_STAGE1_LATENCY` Prometheus metric wired
- feat(sql): `src/infrastructure/erp/query_validator.py` — Stage 2: `ValidationReport`; blocks non-SELECT, 10 injection patterns, missing `tenant_id`; `SQL_STAGE2_ERRORS` metric wired
- feat(sql): `src/infrastructure/erp/query_executor.py` — Stage 3: `ExecutionResult` with unique `query_id`; raises `TenantFilterMissingError` when `has_tenant_filter=False`; `SQL_STAGE3_ROWS` metric wired
- feat(sql): `src/infrastructure/erp/query_log_repository.py` — `InMemoryQueryLogRepository` + `MongoQueryLogRepository`; every `ExecutionResult` logged
- fix(evaluation): `evaluation/benchmarks/sql_benchmark.py` — fix `generate_sql()` to extract `.raw_sql` from `QueryGenerator` result
- test(fixtures): `src/tests/fixtures/.env.test` + `seed_erp_test.sql` — reproducible ERP test DB seed covering FERZA and ACME tenants
- test(unit): `src/tests/unit/test_sql_validator.py` — 44 tests covering all Stage 2 validation rules
- test(integration): `src/tests/integration/test_sql_generator.py` — 10 NL queries verified for SELECT, tenant_id filter, table mapping, metrics
- test(integration): `src/tests/integration/test_sql_pipeline.py` — tenant guard: `TenantFilterMissingError` raised before Stage 3; counter increments verified
- test(integration): `src/tests/integration/test_sql_executor.py` — Stage 3 execution: `query_id` uniqueness, `QueryLogRepository` logging, `InMemoryExecutor` table patterns
- test(integration): `src/tests/integration/test_sql_e2e.py` — full 3-stage E2E: 5 NL queries × NL→SQL→Validate→Execute; Prometheus metrics at each stage

### Definition of Done — Sprint 4 ✓
- `ValidationReport.has_tenant_filter=False` → `TenantFilterMissingError` — Stage 3 never executes
- All non-SELECT SQL (INSERT/UPDATE/DELETE/DROP/DDL) caught by Stage 2 — Stage 3 never reached
- Every `ExecutionResult` has a unique `query_id` logged to `QueryLogRepository`
- SQL pipeline metrics visible: `sql_stage1_latency`, `sql_stage2_errors`, `sql_stage3_rows`
- 321 tests total — all green
- Sprint tag `sprint-4-done` pushed, CHANGELOG updated

---

## [sprint-3-done] — 2026-04-09

### Added
- feat(di): `src/infrastructure/di/container.py` — `DIContainer` with `validate()` that raises `MissingBindingError` listing all unbound required ports; app refuses to start if validation fails
- feat(di): `src/infrastructure/di/factory.py` — `build_container()` wires JWT + UserRepo + AuthUseCase; calls `validate()` before returning
- feat(auth): `src/infrastructure/auth/jwt_handler.py` — RS256 JWT issuance + verification; `TokenExpiredError`, `TokenInvalidError`, `TokenAlgorithmError` with clear messages
- feat(auth): `src/infrastructure/auth/user_repository.py` — `InMemoryUserRepository` with sha256_crypt password hashing; `create`, `verify_password`, `save_reset_token`, `reset_password`
- feat(auth): `src/use_cases/auth_user.py` — `AuthUseCase` orchestrating register, login, request-password-reset, reset-password flows
- feat(routes): `src/routes/auth.py` — `POST /auth/register`, `/auth/login`, `/auth/request-password-reset`, `/auth/reset-password`
- feat(middleware): `src/middleware/AuthMiddleware.py` — upgraded from Sprint 1 stub to full RS256 verification; injects `user_id`, `role`, `tenant_id` into `request.state`
- test(fixtures): `src/tests/fixtures/jwt_fixtures.py` — ephemeral RSA key pair generation; no real IdP required
- test(integration): `src/tests/integration/test_auth_flow.py` — 21 tests: register→login→use token happy path + all 401 cases (expired, missing, tampered, wrong algo) + full password reset flow
- test(integration): `src/tests/integration/test_rbac.py` — 18 tests: all 4 roles (ADMIN/MANAGER/ANALYST/VIEWER) × all route categories; privilege isolation verified
- test(unit): `src/tests/unit/test_di_factory.py` — 16 tests: container validation, factory wiring, AuthUseCase with mocked dependencies

### Definition of Done — Sprint 3 ✓
- `container.validate()` called at startup — app refuses to start with missing port binding
- Full auth integration test: `POST /auth/login` returns JWT → `GET /api/erp/query` with JWT → 200
- All 4 RBAC roles tested: each role only accesses permitted routes (403 on others)
- All token failure cases return 401 with clear error message
- DI factory unit test: use case constructed with mocked dependencies — no real DB needed
- 186 tests total — all green
- Sprint tag `sprint-3-done` pushed, CHANGELOG updated

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
