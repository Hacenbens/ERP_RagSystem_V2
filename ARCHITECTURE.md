# ERP Agentic RAG — Architecture Reference

> Source of truth: `erp_rag_claude_code/docs/source_of_truth.md`
> Code references verified against Sprint 5 branch (`sprint-5/middleware-hardening`).

---

## 1. Middleware Stack

Every HTTP request passes through **five middleware layers** in the order shown below.
`add_middleware()` in Starlette/FastAPI is LIFO, so the last-added class is outermost.

```
Incoming request
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 1 — LoggingMiddleware                            │
│  src/middleware/LoggingMiddleware.py                    │
│  • Generates / propagates X-Request-ID (trace_id)      │
│  • Binds trace_id + user_id into async log context      │
│  • Emits one structured JSON log line per request       │
│  • Increments REQUEST_LATENCY histogram + REQUEST_COUNT │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2 — AuthMiddleware                               │
│  src/middleware/AuthMiddleware.py                       │
│  • Validates JWT RS256 Bearer token on every            │
│    non-public path                                      │
│  • Injects user_id, role, tenant_id into request.state │
│  • Returns 401 on missing / expired / tampered tokens   │
│  • Increments AUTH_FAILURE_RATE + MIDDLEWARE_VIOLATIONS │
│    (middleware="auth")                                  │
│  Public paths (no token required):                      │
│    /health  /auth/login  /auth/register                 │
│    /auth/request-password-reset  /auth/reset-password  │
│    /metrics                                             │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3 — RateLimitMiddleware                          │
│  src/middleware/RateLimitMiddleware.py                  │
│  • Per-user sliding-window:  60 req / min → 429         │
│  • Per-IP  sliding-window: 200 req / min → 429          │
│  • User limit evaluated first; IP limit second          │
│  • Returns Retry-After: 60 header on 429                │
│  • Increments MIDDLEWARE_VIOLATIONS                     │
│    (middleware="rate_limit_user" | "rate_limit_ip")     │
│  • Counters are per-instance (no cross-test pollution)  │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 4 — RBACMiddleware  [+ ModuleAccessGuard]        │
│  src/middleware/RBACMiddleware.py                       │
│  • Guard 1 — Admin route: /admin/* → SUPER_ADMIN only   │
│  • Guard 2 — SQL module guard on /api/erp/query:        │
│      a. REPORTING_ANALYST → always 403 (RAG-only role)  │
│      b. request.state.erp_module set → checks           │
│         MODULE_ACCESS_MATRIX.can_sql                    │
│      c. request.state.erp_table set → resolves module   │
│         via _TABLE_MODULE_MAP → checks can_sql          │
│  • Returns 403 on violation                             │
│  • Increments RBAC_VIOLATION_RATE + MIDDLEWARE_VIOLATIONS│
│    (middleware="rbac_module")                           │
│                                                         │
│  NOTE: ModuleAccessGuard is embedded in this class —    │
│  it is NOT a separate file (Architecture Mapping § 8.3) │
│  Policy data lives in:                                  │
│  src/infrastructure/auth/erp_rbac_policy.py             │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 5 — PIIMaskingMiddleware  (innermost)            │
│  src/middleware/PIIMaskingMiddleware.py                  │
│  • Intercepts POST requests with JSON body              │
│  • Scans "query" field for DZ-specific PII patterns:    │
│      email       RFC 5322 local@domain                  │
│      phone_dz    +213 / 0[5-7]XXXXXXXX                  │
│      nid_dz      18-digit Algerian national ID          │
│      tax_id_dz   15-digit NIF                           │
│  • Replaces hits with [REDACTED:<type>]                 │
│  • Increments PII_DETECTION_RATE per entity type        │
│  • Increments MIDDLEWARE_VIOLATIONS (middleware="pii")  │
│    once per request with ≥ 1 hit (not per entity)       │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
                  Route handler
                  (SQL pipeline / RAG agent)
```

### Stack registration order (LIFO)

```python
# In the FastAPI app factory — last added = outermost = first to evaluate
app.add_middleware(PIIMaskingMiddleware)   # layer 5 — innermost
app.add_middleware(RBACMiddleware)        # layer 4
app.add_middleware(RateLimitMiddleware)   # layer 3
app.add_middleware(AuthMiddleware)        # layer 2
app.add_middleware(LoggingMiddleware)     # layer 1 — outermost
```

### Short-circuit guarantee

A request blocked by any layer **never reaches a lower layer or the route handler**.
Verified by `src/tests/integration/test_middleware_order.py` (Sprint 5, Task 7):

- Auth 401 → `SQL_STAGE1_LATENCY` and `SQL_STAGE3_ROWS` stay flat
- RBAC 403 → route handler sentinel never called

---

## 2. RBAC Decision Matrix

### 2.1 Roles

Defined in `src/domain/user_role.py` (enum `UserRole`).

| Role | SQL access | Notes |
|---|---|---|
| `SUPER_ADMIN` | All modules | Only role permitted on `/admin/*` |
| `PRODUCT_MANAGER` | inventory, procurement, CRM | RAG-only on reporting |
| `INVENTORY_MANAGER` | inventory, warehouse | RAG-only on reporting |
| `FINANCE_MANAGER` | finance, reporting | Full SQL on both |
| `WAREHOUSE_OPERATOR` | warehouse | RAG-only on inventory |
| `PROCUREMENT_MANAGER` | procurement, inventory | RAG-only on finance, reporting |
| `CRM_AGENT` | CRM | RAG-only on reporting |
| `LOGISTICS_AGENT` | logistics, warehouse | RAG-only on reporting |
| `REPORTING_ANALYST` | **none** | RAG-only on all modules; SQL always denied |

### 2.2 MODULE_ACCESS_MATRIX

Defined in `src/infrastructure/auth/erp_rbac_policy.py`.

Legend: `SQL+RAG` = full access · `RAG` = read-only via RAG · `—` = no access

| Role | inventory | finance | warehouse | procurement | crm | logistics | reporting | admin |
|---|---|---|---|---|---|---|---|---|
| SUPER_ADMIN | SQL+RAG | SQL+RAG | SQL+RAG | SQL+RAG | SQL+RAG | SQL+RAG | SQL+RAG | SQL+RAG |
| PRODUCT_MANAGER | SQL+RAG | — | — | SQL+RAG | SQL+RAG | — | RAG | — |
| INVENTORY_MANAGER | SQL+RAG | — | SQL+RAG | — | — | — | RAG | — |
| FINANCE_MANAGER | — | SQL+RAG | — | — | — | — | SQL+RAG | — |
| WAREHOUSE_OPERATOR | RAG | — | SQL+RAG | — | — | — | — | — |
| PROCUREMENT_MANAGER | SQL+RAG | RAG | — | SQL+RAG | — | — | RAG | — |
| CRM_AGENT | — | — | — | — | SQL+RAG | — | RAG | — |
| LOGISTICS_AGENT | — | — | SQL+RAG | — | — | SQL+RAG | RAG | — |
| REPORTING_ANALYST | RAG | RAG | RAG | RAG | RAG | RAG | RAG | RAG |

### 2.3 SQL Table → Module mapping

Defined in `_TABLE_MODULE_MAP` (`erp_rbac_policy.py`).
Used by `is_table_allowed(role, table_name)` when `request.state.erp_table` is set.

| Module | SQL tables |
|---|---|
| inventory | `inventory`, `products`, `returns`, `production_batches`, `quality_checks` |
| finance | `invoices`, `accounts_receivable`, `vat_transactions`, `budget_actuals`, `payroll`, `assets`, `sales_orders` |
| warehouse | `warehouses`, `bins` |
| procurement | `purchase_orders`, `suppliers`, `contracts` |
| crm | `customers`, `crm_interactions` |
| logistics | `shipments`, `delivery_routes` |
| admin | `employees`, `users`, `leave_balances` |

### 2.4 RAG Collection → Module mapping

Defined in `_COLLECTION_MODULE_MAP` (`erp_rbac_policy.py`).
Used by `is_collection_allowed(role, collection_name)`.

| Collection | Module |
|---|---|
| `inventory_docs` | inventory |
| `finance_docs` | finance |
| `warehouse_docs` | warehouse |
| `procurement_docs` | procurement |
| `crm_docs` | crm |
| `logistics_docs` | logistics |
| `reporting_docs` | reporting |
| `admin_docs` | admin |
| `sop_collection` | admin |
| `bpmn_collection` | admin |
| `tax_collection` | finance |

Unknown collections are denied for all roles except `SUPER_ADMIN`.

### 2.5 ModuleAccessGuard — design note

> `ModuleAccessGuard` is **embedded inside `RBACMiddleware`** as the private method
> `_check_sql_module_guard()`. It is **not** a separate file or class.
> This is a deliberate Architecture Mapping decision (§ 8.3) to keep the guard
> co-located with the enforcement point and avoid an unnecessary abstraction layer.

Policy lookup is delegated to `erp_rbac_policy.py` via three public functions:

| Function | Called when |
|---|---|
| `get_allowed_modules(role)` | Evaluating module-level permission |
| `is_table_allowed(role, table)` | `request.state.erp_table` is set |
| `is_collection_allowed(role, coll)` | RAG collection access check |

---

## 3. Prometheus Metrics Reference

Every metric below is emitted by production code. That is enforced, not
asserted — see [ADR-001](docs/adr/ADR-001-no-dead-or-duplicate-code.md) and
`TestEveryMetricIsEmitted`. A metric nothing writes to reports a permanent
zero, which on a dashboard reads as "measured, and healthy".

### Request path

| Metric | Type | Labels | Emitted by |
|---|---|---|---|
| `erp_rag_requests_total` | Counter | method, endpoint, status_code | LoggingMiddleware |
| `erp_rag_request_latency_seconds` | Histogram | method, endpoint, status_code | LoggingMiddleware |
| `erp_rag_auth_failures_total` | Counter | reason | AuthMiddleware |
| `erp_rag_middleware_violations_total` | Counter | middleware | Auth / RateLimit / RBAC / PII layers |
| `erp_rag_rbac_violations_total` | Counter | role, resource | RBACMiddleware |
| `erp_rag_pii_detections_total` | Counter | entity_type | PIIMaskingMiddleware |

`MIDDLEWARE_VIOLATIONS` label values: `auth` · `rate_limit_user` · `rate_limit_ip` · `rbac_module` · `pii`

### Query pipeline — per stage

| Metric | Type | Labels | Emitted by |
|---|---|---|---|
| `erp_rag_query_stage_latency_ms` | Histogram | stage | `stage_timer()` — the only way a stage reports latency |
| `erp_rag_tokens_used_total` | Counter | provider, type | GeminiLLMClient, vLLMLLMClient |

`stage` label values, from `observability.stage_timer.Stage`:

| Stage | Measures | Emitted in |
|---|---|---|
| `classify` | NL query → routing decision | `use_cases/route_query.py` |
| `retrieve` | embed query + vector search | `infrastructure/rag/vector_retriever.py` |
| `rerank` | cross-encoder re-scoring | `agents/rag_agent.py` |
| `generate` | RAG answer generation | `agents/rag_agent.py` |
| `merge` | hybrid RAG+SQL merge call | `agents/hybrid_agent.py` |
| `sql_generate` | NL → SQL | `infrastructure/erp/query_generator.py` |
| `sql_execute` | SQL → rows | `infrastructure/erp/query_executor.py` |

Tokens come from the LLM clients because they are the only layer that sees what
a provider actually charged. Counting higher up would mean estimating, and an
estimate reported as a measurement is worse than no number. A provider that
reports no usage records nothing — `None` is not `0`.

**`stage_latency` does not replace `request_latency` or `hybrid_latency`.**
Those are end-to-end wall clock. RAG and SQL run concurrently inside the hybrid
pipeline, so the total is *not* the sum of the stages; the gap between them is
the parallelism actually achieved, and it is worth seeing.

### SQL pipeline

| Metric | Type | Labels | Emitted by |
|---|---|---|---|
| `erp_rag_sql_stage2_errors_total` | Counter | reason | QueryValidator |
| `erp_rag_sql_stage3_rows_returned` | Histogram | — | QueryExecutor |
| `erp_rag_sql_pipeline_errors_total` | Counter | stage | QueryGenerator, QueryExecutor |

Stage 1 latency was once its own metric, `erp_rag_sql_stage1_latency_seconds`,
recording **seconds** while nothing else recorded stage latency at all. It is
now `erp_rag_query_stage_latency_ms{stage="sql_generate"}`, in milliseconds,
like every other stage.

### Workers

| Metric | Type | Labels | Emitted by |
|---|---|---|---|
| `erp_rag_worker_tasks_dispatched_total` | Counter | task_name | ingest_task |
| `erp_rag_worker_tasks_failed_total` | Counter | task_name | ingest_task |
| `erp_rag_worker_task_duration_seconds` | Histogram | task_name | ingest_task |
| `erp_rag_embed_tasks_dispatched_total` | Counter | task_name | embed_task |
| `erp_rag_embed_tasks_failed_total` | Counter | task_name | embed_task |
| `erp_rag_embed_task_duration_seconds` | Histogram | task_name | embed_task |

### Agents and LLM health

| Metric | Type | Labels | Emitted by |
|---|---|---|---|
| `erp_rag_hybrid_successes_total` | Counter | — | HybridAgent |
| `erp_rag_hybrid_latency_seconds` | Histogram | — | HybridAgent (end-to-end) |
| `erp_rag_llm_failures_total` | Counter | provider | ModelSelector |
| `erp_rag_circuit_breaker_open` | Gauge | provider | ModelSelector |
| `erp_rag_degraded_mode_activations_total` | Counter | — | DegradedModeService |

---

## 4. External Server Setup (Kaggle / self-hosted)

See [`notebooks/kaggle_llm_server.ipynb`](notebooks/kaggle_llm_server.ipynb) for step-by-step instructions on starting the vLLM OpenAI-compatible server (port 8000) and the embedding server (port 8001) on a Kaggle GPU instance.
