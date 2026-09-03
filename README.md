# ERP Agentic RAG System

A multi-tenant, role-aware question-answering system for ERP data.
Natural-language queries are automatically classified and routed to a **RAG pipeline** (document search), a **SQL pipeline** (live ERP database queries), or both in **Hybrid** mode.

---

## Table of Contents

1. [How the system works](#how-the-system-works)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Environment variables](#environment-variables)
5. [Running the server](#running-the-server)
6. [API reference](#api-reference)
   - [Auth](#auth)
   - [Query](#query)
   - [Assets](#assets)
   - [Admin](#admin)
7. [Roles and permissions](#roles-and-permissions)
8. [ERP modules and SQL tables](#erp-modules-and-sql-tables)
9. [Query intents](#query-intents)
10. [Running the tests](#running-the-tests)

---

## How the system works

```
User sends a natural-language question
        │
        ▼
┌─────────────────────┐
│   AuthMiddleware    │  Validates RS256 JWT — rejects with 401 if missing/expired
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│   RBACMiddleware    │  Checks role × ERP module permissions — rejects with 403
└─────────────────────┘
        │
        ▼
┌────────────────────────────────┐
│   QueryClassifierAgent (LLM)   │  Classifies intent: RAG | SQL | HYBRID | BLOCKED
└────────────────────────────────┘
        │
   ┌────┴────┐
   ▼         ▼
RAGAgent   SQLAgent          (run in parallel for HYBRID)
   │         │
   │         ├─ Stage 1: QueryGenerator  — NL → SQL (via Gemini)
   │         ├─ Stage 2: QueryValidator  — tenant_id filter check
   │         └─ Stage 3: QueryExecutor   — runs against ERP PostgreSQL
   │
   └─ Vector search → context chunks → LLM answer generation
        │
        ▼
┌─────────────────────┐
│    HybridAgent      │  Merges RAG answer + SQL result table
└─────────────────────┘
        │
        ▼
    JSON response  →  intent + answer + cited chunks / SQL tables used
```

**Document ingestion** runs asynchronously:

```
POST /api/assets/upload
        │
        ▼
File saved to local storage (ASSET_STORAGE_PATH)
        │
        ▼
Celery ingest job dispatched (broker: Redis)
        │
        ▼
Chunker → Embedder → MilvusVectorStore (upsert with tenant isolation)
```

---

## Prerequisites

- Python 3.11+
- Redis (Celery broker — `redis-cli ping` should return `PONG`)
- A Gemini API key (free tier: `gemini-2.5-flash-lite`)
- Optional: PostgreSQL ERP database for live SQL queries
- Optional: Milvus server or Milvus Lite `.db` file for persistent vector search

---

## Installation

```bash
# Clone the repo
git clone <repo-url>
cd ERP_RagSystem_V2

# Create and activate the virtual environment
python -m venv erp-rag-env-v2
source erp-rag-env-v2/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install uvicorn python-dotenv
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key (primary LLM) |
| `GEMINI_MODEL` | No | Model name (default: `gemini-2.5-flash-lite`) |
| `JWT_SECRET_KEY` | Yes | Secret used to sign JWTs — change in production |
| `REDIS_URL` | No | Celery broker URL (default: `redis://localhost:6379/0`) |
| `ASSET_STORAGE_PATH` | No | Local path for uploaded files (default: `/tmp/erp_rag_assets`) |
| `MILVUS_DB_URI` | No | Milvus server URI or Milvus Lite `.db` path — omit for in-memory fallback. Not named `MILVUS_URI`: pymilvus claims that name and rejects file paths. |
| `MONGODB_URI` | No | MongoDB connection string — omit for in-memory fallback |
| `NGROK_BASE_URL` | No | Ngrok-tunnelled embedding server — omit for no-op embeddings |
| `VLLM_BASE_URL` | No | vLLM fallback endpoint |
| `ERP_PG_HOST` | No | ERP PostgreSQL host for live SQL queries |
| `ERP_PG_PASSWORD` | No | ERP PostgreSQL password |

---

## Running the server

```bash
source erp-rag-env-v2/bin/activate
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

**Interactive API docs (Swagger UI):**
```
http://localhost:8000/docs
```

**ReDoc:**
```
http://localhost:8000/redoc
```

**How to authenticate in Swagger:**
1. Call `POST /auth/register` to create a user
2. Call `POST /auth/login` — copy the `access_token` from the response
3. Click the **Authorize 🔒** button at the top of the Swagger page
4. Enter `Bearer <your_token>` and confirm

---

## API reference

### Auth

All auth routes are public (no JWT required).

---

#### `POST /auth/register`

Create a new user account.

**Request body:**

```json
{
  "username": "alice",
  "password": "mypassword123",
  "role": "FINANCE_MANAGER",
  "tenant_id": "acme-corp"
}
```

| Field | Type | Rules |
|---|---|---|
| `username` | string | 3–64 characters |
| `password` | string | minimum 8 characters |
| `role` | string | one of the 9 roles listed in [Roles](#roles-and-permissions) |
| `tenant_id` | string | any non-empty string — isolates data per organisation |

**Response `201`:**

```json
{
  "user_id": "cd8cb3ca-0ab9-4e43-bf7a-3b657b23a985",
  "username": "alice",
  "role": "FINANCE_MANAGER",
  "tenant_id": "acme-corp"
}
```

---

#### `POST /auth/login`

Authenticate and receive a JWT.

**Request body:**

```json
{
  "username": "alice",
  "password": "mypassword123"
}
```

**Response `200`:**

```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "user_id": "cd8cb3ca-...",
  "role": "FINANCE_MANAGER",
  "tenant_id": "acme-corp"
}
```

The token expires in 60 minutes (configurable via `JWT_EXPIRY_MINUTES`).

---

#### `POST /auth/request-password-reset`

Request a password reset token.

**Request body:**

```json
{ "username": "alice" }
```

**Response `200`:**

```json
{
  "reset_token": "aEWDrTL...",
  "message": "Password reset token issued. Use POST /auth/reset-password."
}
```

---

#### `POST /auth/reset-password`

Set a new password using the reset token.

**Request body:**

```json
{
  "reset_token": "aEWDrTL...",
  "new_password": "newpassword123"
}
```

**Response `200`:**

```json
{ "message": "Password reset successfully." }
```

---

### Query

Requires a valid JWT in the `Authorization: Bearer <token>` header.

---

#### `POST /api/v1/query`

Send a natural-language question. The system classifies the intent and routes it through the appropriate pipeline.

**Request body:**

```json
{
  "query": "What are the open invoices for this month?",
  "erp_module": "finance"
}
```

| Field | Type | Rules |
|---|---|---|
| `query` | string | 1–2000 characters |
| `erp_module` | string | optional — one of the 8 ERP modules; narrows SQL table access |

**Response `200` — RAG intent:**

```json
{
  "intent": "RAG",
  "result": {
    "grounded": true,
    "answer": "There are 12 open invoices totalling 45,000 DZD...",
    "cited_chunks": ["chunk-id-1", "chunk-id-2"],
    "grounding_score": 0.87,
    "confidence": 0.91,
    "insufficient_data_for": []
  },
  "rag_only": false,
  "sql_only": false
}
```

**Response `200` — SQL intent:**

```json
{
  "intent": "SQL",
  "result": {
    "sql": "SELECT * FROM invoices WHERE tenant_id = :tenant_id AND status = 'open'",
    "rows": [...],
    "row_count": 12,
    "latency_ms": 54.3
  },
  "rag_only": false,
  "sql_only": true
}
```

**Response `200` — HYBRID intent:**

```json
{
  "intent": "HYBRID",
  "result": {
    "rag_result": { ... },
    "sql_result": { ... },
    "merged_answer": "Based on documents and live data...",
    "overall_confidence": 0.83
  },
  "rag_only": false,
  "sql_only": false
}
```

**Error responses:**

| Code | Reason |
|---|---|
| `401` | Missing or invalid JWT |
| `403` | Role not permitted on this module or path (`BLOCKED` intent) |
| `503` | Both RAG and SQL agents failed simultaneously |

---

### Assets

Requires a valid JWT. Used to upload ERP documents for RAG ingestion.

---

#### `POST /api/assets/upload`

Upload a document. The file is saved and an async ingestion job is dispatched (chunking → embedding → vector store).

**Request:** `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | file | Any text document (PDF, DOCX, TXT, etc.) |
| `chunk_strategy` | string | `sop` (default), `bpmn`, or `tax` |

**Example with curl:**

```bash
curl -X POST http://localhost:8000/api/assets/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/document.pdf" \
  -F "chunk_strategy=sop"
```

**Response `202`:**

```json
{
  "asset_id": "8b743e3a-b243-45cb-a9ec-562373594529",
  "job_id": "c5e76d8e-2fff-40a3-b062-9753b5d63223",
  "filename": "purchase_policy.pdf",
  "size_bytes": 84210,
  "chunk_strategy": "sop"
}
```

Use the `job_id` to poll processing status via `GET /admin/jobs/{job_id}`.

---

### Admin

`GET /admin/*` routes require the `SUPER_ADMIN` role.

---

#### `GET /admin/jobs/{job_id}`

Poll the status of a background ingestion or embedding job.

**Response `200`:**

```json
{
  "job_id": "c5e76d8e-...",
  "status": "SUCCESS",
  "result": { "chunks_created": 14, "embeddings_stored": 14 },
  "error": null
}
```

| `status` value | Meaning |
|---|---|
| `PENDING` | Job queued, not yet picked up by a worker |
| `STARTED` | Worker is processing |
| `SUCCESS` | Completed — check `result` |
| `FAILURE` | Failed after all retries — check `error` |
| `RETRY` | Being retried |
| `REVOKED` | Cancelled |

---

#### `GET /health`

Public liveness check.

**Response `200`:**
```json
{ "status": "ok" }
```

---

## Roles and permissions

| Role | SQL access | RAG access | Permitted modules |
|---|---|---|---|
| `SUPER_ADMIN` | All modules | All modules | Everything |
| `PRODUCT_MANAGER` | inventory, procurement, CRM | + reporting | inventory, procurement, crm, reporting |
| `INVENTORY_MANAGER` | inventory, warehouse | + reporting | inventory, warehouse, reporting |
| `FINANCE_MANAGER` | finance, reporting | Same | finance, reporting |
| `WAREHOUSE_OPERATOR` | warehouse | + inventory | warehouse, inventory |
| `PROCUREMENT_MANAGER` | procurement, inventory | + finance, reporting | procurement, inventory, finance, reporting |
| `CRM_AGENT` | crm | + reporting | crm, reporting |
| `LOGISTICS_AGENT` | logistics, warehouse | + reporting | logistics, warehouse, reporting |
| `REPORTING_ANALYST` | **None (always denied)** | All modules | all (RAG only) |

A `403` is returned when a role attempts SQL on a module it cannot access, or when any role other than `SUPER_ADMIN` accesses `/admin/*`.

---

## ERP modules and SQL tables

| Module | SQL tables |
|---|---|
| `inventory` | inventory, products, returns, production_batches, quality_checks |
| `finance` | invoices, accounts_receivable, vat_transactions, budget_actuals, payroll, assets, sales_orders |
| `warehouse` | warehouses, bins |
| `procurement` | purchase_orders, suppliers, contracts |
| `crm` | customers, crm_interactions |
| `logistics` | shipments, delivery_routes |
| `reporting` | budget_actuals (cross-module aggregates) |
| `admin` | employees, users, leave_balances |

Pass `erp_module` in the query body to constrain which tables the SQL generator may use.

---

## Query intents

| Intent | When | What happens |
|---|---|---|
| `RAG` | Conceptual / policy questions | Searches uploaded documents, generates a grounded answer |
| `SQL` | Data retrieval questions | Generates SQL → validates tenant filter → executes against ERP PostgreSQL |
| `HYBRID` | Mixed questions | Runs RAG and SQL in parallel, merges results |
| `BLOCKED` | Out-of-scope or harmful input | Returns `403` with reason |

---

## Running the tests

```bash
source erp-rag-env-v2/bin/activate
pytest src/tests/ -v
```

Run only unit tests:

```bash
pytest src/tests/unit/ -v
```

Run only integration tests:

```bash
pytest src/tests/integration/ -v
```
