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

| Metric | Type | Labels | Incremented by |
|---|---|---|---|
| `erp_rag_requests_total` | Counter | method, endpoint, status_code | LoggingMiddleware |
| `erp_rag_request_latency_seconds` | Histogram | method, endpoint, status_code | LoggingMiddleware |
| `erp_rag_auth_failures_total` | Counter | reason | AuthMiddleware |
| `erp_rag_middleware_violations_total` | Counter | middleware | Auth / RateLimit / RBAC / PII layers |
| `erp_rag_rbac_violations_total` | Counter | role, resource | RBACMiddleware |
| `erp_rag_pii_detections_total` | Counter | entity_type | PIIMaskingMiddleware |

`MIDDLEWARE_VIOLATIONS` label values: `auth` · `rate_limit_user` · `rate_limit_ip` · `rbac_module` · `pii`

---

## 4. External Server Setup (Kaggle / self-hosted)

See [`notebooks/kaggle_llm_server.ipynb`](notebooks/kaggle_llm_server.ipynb) for step-by-step instructions on starting the vLLM OpenAI-compatible server (port 8000) and the embedding server (port 8001) on a Kaggle GPU instance.
