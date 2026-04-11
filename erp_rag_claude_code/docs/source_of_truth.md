# ERP Agentic RAG — Source of Truth
_Auto-generated from DOCX files. Do not edit manually._

---
# DOCUMENT 1: Architecture Mapping
---

ERP AGENTIC RAG SYSTEM
Architecture Mapping & Updated Engineering Document
Actual Codebase  →  Document Architecture  |  April 2026  |  FERZA ERP Platform
Property | Value
Document Type | Architecture Mapping — Actual Code ↔ Engineering Spec
Codebase Stack | FastAPI · Python 3.13 · MongoDB · Milvus · Celery · Redis
Document Stack | FastAPI · Python 3.11 · PostgreSQL 17 (read-only) · Milvus
SQL Pipeline | query_generator → query_validator (report) → query_executor (result)
Auth | JWT RS256 · RBAC · PII Masking · Rate Limiting
Workers | Celery (ingest_task, embed_task) · Chunker Factory
Storage | MongoDB (chunks/assets/projects) · Milvus (vectors) · Local/MinIO
Status | Mapping v1.0 — Reconciles actual code with architecture spec


## 1. Structure Overview — Old vs New
This document maps the actual codebase (discovered from the file tree) to the architecture described in the engineering specification. Both structures use Clean Architecture but differ in several concrete areas: the actual code uses MongoDB where the spec assumed PostgreSQL, uses Celery workers for async processing, and has an extended middleware stack with rate limiting.
CRITICAL DIFFERENCE: The SQL pipeline in the actual codebase is a three-stage pipeline: (1) query_generator.py generates the SQL, (2) query_validator.py produces a validation report, (3) query_executor.py executes and returns the result. This replaces the simpler two-step generate→execute pattern described in the spec.


### 1.1 — High-Level Layer Comparison
Architecture Layer | Spec (Document) | Actual Code | Delta
API Framework | FastAPI | FastAPI (main.py) | No change
Database | PostgreSQL 17 (read-only) | MongoDB (motor) + Milvus | DIFFERENT — MongoDB not PG
SQL Target | ERP PostgreSQL schemas | External ERP PG (via query_executor.py) | Same intent, different location
Auth | JWT RS256 middleware | AuthMiddleware.py + jwt_handler.py | Implemented
RBAC | RBACMiddleware | RBACMiddleware.py + erp_rbac_policy.py | Implemented + ERP policy added
PII | PIIMiddleware | PIIMaskingMiddleware.py + pii_masking_service.py | Implemented
Rate Limiting | Not specified | RateLimitMiddleware.py | EXTRA — not in spec
Async Workers | Not specified | Celery (celery_app.py, tasks/) | EXTRA — Celery not in spec
Chunking | RecursiveCharacterTextSplitter | Chunker Factory (sop/bpmn/tax_circular) | RICHER — domain-aware chunkers
Embeddings | text-embedding-3-large | httpx_embedding_provider.py (external) | Abstracted behind port
LLM | OpenAI GPT-4o | openai_llm_client.py + vllm_llm_client.py | Both OpenAI + vLLM self-hosted
DI Container | Not specified | di/container.py + di/factory.py | EXTRA — proper DI wiring
Audit Log | Not specified | mongo_audit_log.py + audit_events.py | EXTRA — full audit trail


## 2. Complete File Path Mapping
Each row maps a file or folder from the actual codebase to its equivalent concept in the engineering specification. Files marked NEW exist in the codebase but were not described in the spec. Files marked REPLACED exist in the spec but are implemented differently in the code.

### 2.1 — Domain Layer
Old Path (Actual) |  | New Path (Document) | Notes
src/domain/models/erp/Sku.py | → | domain/models/mdm_sku.py | Same entity — different path convention
src/domain/models/erp/Supplier.py | → | domain/models/mdm_supplier.py | Same entity
src/domain/models/erp/TaxRule.py | → | domain/models/mdm_tax_rule.py | Same entity
src/domain/models/erp/Wilaya.py | → | domain/models/mdm_wilaya.py | Same entity
src/domain/models/erp/Bin.py | → | domain/models/mdm_bin.py | Same entity
src/domain/models/erp/Product.py | → | domain/models/pim_product.py | Same entity
src/domain/models/erp/Variant.py | → | domain/models/pim_variant.py | Same entity
src/domain/models/erp/Order.py | → | domain/models/oms_order.py | Same entity
src/domain/models/erp/Customer.py | → | domain/models/crm_customer.py | Same entity
src/domain/models/erp/erp_schema.py | → | domain/models/erp_schema.py | Schema registry — already flat in spec
src/domain/models/sql_pipeline.py | → | domain/models/sql_pipeline.py | NEW — models for 3-stage pipeline result
src/domain/models/query_log.py | → | domain/models/query_log.py | NEW — not in spec, added for audit
src/domain/models/pii_entity.py | → | domain/models/pii_entity.py | NEW — structured PII detection result
src/domain/models/audit_events.py | → | domain/models/audit_events.py | NEW — audit trail events
src/domain/models/user.py | → | domain/models/user.py | NEW — user entity for auth
src/domain/exceptions.py | → | domain/exceptions/*.py | Centralised domain exceptions


### 2.2 — Domain Ports
Old Path (Actual) |  | New Path (Document) | Notes
src/domain/ports/llm_client.py | → | domain/ports/llm_port.py | Renamed — same ABC
src/domain/ports/vector_store.py | → | domain/ports/vector_store_port.py | Renamed — same ABC
src/domain/ports/embedding_provider.py | → | domain/ports/embedding_port.py | Same ABC
src/domain/ports/reranker.py | → | domain/ports/reranker_port.py | Same ABC
src/domain/ports/chunk_store.py | → | domain/ports/chunk_store_port.py | Same ABC
src/domain/ports/asset_repository.py | → | domain/ports/asset_repository_port.py | Same ABC
src/domain/ports/project_repository.py | → | domain/ports/project_repository_port.py | Same ABC
src/domain/ports/user_repository.py | → | domain/ports/user_repository_port.py | NEW — not in spec
src/domain/ports/query_log_repository.py | → | domain/ports/query_log_repository_port.py | NEW — not in spec
src/domain/ports/sql_generator_port.py | → | domain/ports/sql_generator_port.py | Stage 1 of SQL pipeline
src/domain/ports/sql_validator_port.py | → | domain/ports/sql_validator_port.py | Stage 2 — produces ValidationReport
src/domain/ports/sql_executor_port.py | → | domain/ports/sql_executor_port.py | Stage 3 — produces ExecutionResult
src/domain/ports/query_classifier_port.py | → | domain/ports/query_classifier_port.py | Query router ABC
src/domain/ports/query_rewriter_port.py | → | domain/ports/query_rewriter_port.py | NEW — query rewriting before routing
src/domain/ports/query_validator_port.py | → | domain/ports/query_validator_port.py | NEW — pre-execution validation
src/domain/ports/pii_masker_port.py | → | domain/ports/pii_masker_port.py | NEW — PII masking ABC
src/domain/ports/context_builder_port.py | → | domain/ports/context_builder_port.py | RAG context assembly ABC
src/domain/ports/prompt_builder_port.py | → | domain/ports/prompt_builder_port.py | NEW — prompt construction ABC
src/domain/ports/model_selector_port.py | → | domain/ports/model_selector_port.py | NEW — dynamic model selection
src/domain/ports/degraded_mode_port.py | → | domain/ports/degraded_mode_port.py | NEW — fallback when LLM unreachable
src/domain/ports/job_dispatcher_port.py | → | domain/ports/job_dispatcher_port.py | NEW — Celery job dispatch ABC
src/domain/ports/job_status_reader_port.py | → | domain/ports/job_status_reader_port.py | NEW — async job status polling
src/domain/ports/tokenizer.py | → | domain/ports/tokenizer_port.py | NEW — token counting ABC
src/domain/ports/audit_log.py | → | domain/ports/audit_log_port.py | NEW — audit logging ABC
src/domain/ports/asset_storage.py | → | domain/ports/asset_storage_port.py | File storage ABC (local/MinIO)


### 2.3 — Application Use Cases
Old Path (Actual) |  | New Path (Document) | Notes
src/application/use_cases/answer_query.py | → | application/use_cases/route_query.py + answer_*.py | Split into router + typed handlers
src/application/use_cases/process_asset.py | → | application/use_cases/process_asset.py | Same — triggers Celery ingest task
src/application/use_cases/upload_asset.py | → | application/use_cases/upload_asset.py | Same — validates + stores file
src/application/use_cases/create_project.py | → | application/use_cases/create_project.py | Same
src/application/use_cases/delete_project.py | → | application/use_cases/delete_project.py | Same — cascades to chunks/assets
src/application/use_cases/auth_user.py | → | application/use_cases/auth_user.py | NEW — login / token refresh


### 2.4 — Infrastructure: Persistence
Old Path (Actual) |  | New Path (Document) | Notes
src/infrastructure/persistence/mongo_asset_repository.py | → | infrastructure/persistence/mongo_asset_repository.py | MongoDB — NOT PostgreSQL as in spec
src/infrastructure/persistence/mongo_chunk_store.py | → | infrastructure/persistence/mongo_chunk_store.py | MongoDB — NOT PostgreSQL as in spec
src/infrastructure/persistence/mongo_project_repository.py | → | infrastructure/persistence/mongo_project_repository.py | MongoDB
src/infrastructure/persistence/mongo_user_repository.py | → | infrastructure/persistence/mongo_user_repository.py | NEW — user storage
src/infrastructure/persistence/mongo_query_log_repository.py | → | infrastructure/persistence/mongo_query_log_repository.py | NEW — query audit log
src/infrastructure/persistence/mongo_audit_log.py | → | infrastructure/persistence/mongo_audit_log.py | NEW — structured audit events
src/infrastructure/persistence/milvus_vector_store.py | → | infrastructure/persistence/milvus_vector_store.py | Same — vector search
(no file) | ← | infrastructure/persistence/postgres_erp_replica.py | SPEC ONLY — ERP SQL is in erp/ not here


### 2.5 — Infrastructure: ERP SQL Pipeline (3-Stage)
This is the most important structural difference. The spec described a two-step SQL flow. The actual code implements a three-stage pipeline: Generator produces SQL text → Validator produces a ValidationReport (not yet executed) → Executor takes the report and produces an ExecutionResult.

Old Path (Actual) |  | New Path (Document) | Notes
src/infrastructure/erp/query_generator.py | → | infrastructure/erp/query_generator.py | Stage 1 — NL → SQL string (LLM call)
src/infrastructure/erp/query_validator.py | → | infrastructure/erp/query_validator.py | Stage 2 — SQL → ValidationReport (sqlglot + tenant check)
src/infrastructure/erp/query_executor.py | → | infrastructure/erp/query_executor.py | Stage 3 — ValidationReport → ExecutionResult (asyncpg)
src/infrastructure/auth/erp_rbac_policy.py | → | infrastructure/auth/erp_rbac_policy.py | NEW — ERP module permission matrix (imports from domain/enums.py)


### 2.6 — Infrastructure: NLP Services
Old Path (Actual) |  | New Path (Document) | Notes
src/infrastructure/nlp/openai_llm_client.py | → | infrastructure/llm/openai_client.py | Renamed path — same impl
src/infrastructure/nlp/vllm_llm_client.py | → | infrastructure/llm/vllm_client.py | NEW — self-hosted vLLM support
src/infrastructure/nlp/httpx_embedding_provider.py | → | infrastructure/nlp/httpx_embedding_provider.py | External embedding server (Kaggle)
src/infrastructure/nlp/noop_embedding_provider.py | → | infrastructure/nlp/noop_embedding_provider.py | No-op — for testing without GPU
src/infrastructure/nlp/cross_encoder_reranker.py | → | infrastructure/nlp/cross_encoder_reranker.py | BGE cross-encoder reranker
src/infrastructure/nlp/query_classifier.py | → | infrastructure/nlp/query_classifier.py | LLM-based: rag|sql|hybrid|blocked
src/infrastructure/nlp/query_rewriter.py | → | infrastructure/nlp/query_rewriter.py | NEW — rewrites ambiguous queries
src/infrastructure/nlp/query_validator.py | → | infrastructure/nlp/query_validator.py | NEW — semantic pre-validation
src/infrastructure/nlp/pii_masking_service.py | → | infrastructure/nlp/pii_masking_service.py | PII regex masker
src/infrastructure/nlp/language_detection_service.py | → | infrastructure/nlp/language_detection_service.py | NEW — AR/FR/EN detection
src/infrastructure/nlp/tiktoken_tokenizer.py | → | infrastructure/nlp/tiktoken_tokenizer.py | NEW — token counting for context window


### 2.7 — Infrastructure: Generation Services
Old Path (Actual) |  | New Path (Document) | Notes
src/infrastructure/generation/context_builder.py | → | infrastructure/generation/context_builder.py | RAG chunk context assembly
src/infrastructure/generation/prompt_service.py | → | infrastructure/generation/prompt_service.py | Prompt template rendering
src/infrastructure/generation/model_selector.py | → | infrastructure/generation/model_selector.py | NEW — OpenAI vs vLLM routing
src/infrastructure/generation/degraded_mode_service.py | → | infrastructure/generation/degraded_mode_service.py | NEW — fallback when LLM down


### 2.8 — Infrastructure: Security
Old Path (Actual) |  | New Path (Document) | Notes
src/infrastructure/security/jwt_handler.py | → | infrastructure/security/jwt_handler.py | RS256 sign/verify
src/infrastructure/security/password_hasher.py | → | infrastructure/security/password_hasher.py | bcrypt hashing
src/infrastructure/security/permissions.py | → | infrastructure/security/permissions.py | Permission enums + helpers


### 2.9 — Infrastructure: Storage
Old Path (Actual) |  | New Path (Document) | Notes
src/infrastructure/storage/local_asset_storage.py | → | infrastructure/storage/local_asset_storage.py | Local disk — dev/test
src/infrastructure/storage/minio_asset_storage.py | → | infrastructure/storage/minio_asset_storage.py | MinIO S3-compatible — production


### 2.10 — Infrastructure: DI Container (NEW)
The DI container is an addition not described in the spec. It wires all ports to their concrete implementations at startup, removing hardcoded dependencies from routes and use cases.

Old Path (Actual) |  | New Path (Document) | Notes
src/infrastructure/di/container.py | → | infrastructure/di/container.py | NEW — registers all port→implementation bindings
src/infrastructure/di/factory.py | → | infrastructure/di/factory.py | NEW — creates injected use case instances


### 2.11 — Middleware Layer
Old Path (Actual) |  | New Path (Document) | Notes
src/middleware/AuthMiddleware.py | → | interfaces/middleware/auth_middleware.py | JWT RS256 — implemented
src/middleware/LoggingMiddleware.py | → | interfaces/middleware/logging_middleware.py | trace_id + JSON structured logs
src/middleware/PIIMaskingMiddleware.py | → | interfaces/middleware/pii_middleware.py | PII detection + masking
src/middleware/RBACMiddleware.py | → | interfaces/middleware/rbac_middleware.py | Role permission enforcement
src/middleware/RateLimitMiddleware.py | → | interfaces/middleware/rate_limit_middleware.py | NEW — not in spec, throttling
(no file — embedded in RBAC) | ← | interfaces/middleware/module_access_guard.py | SPEC ONLY — module guard merged into RBAC


### 2.12 — Routes & Schemas
Old Path (Actual) |  | New Path (Document) | Notes
src/routes/base.py | → | interfaces/routes/base.py | Health / heartbeat
src/routes/auth.py | → | interfaces/routes/auth.py | Login / token endpoints
src/routes/data.py | → | interfaces/routes/data.py | Upload / process assets
src/routes/projects.py | → | interfaces/routes/projects.py | Project CRUD
src/routes/query.py | → | interfaces/routes/erp_query.py | POST /api/erp/query — main query endpoint
src/routes/admin.py | → | interfaces/routes/admin.py | Metrics / job status
src/routes/schemas/auth.py | → | interfaces/routes/schemas/auth.py | Pydantic request/response models
src/routes/schemas/data.py | → | interfaces/routes/schemas/data.py | Upload schemas
src/routes/schemas/projects.py | → | interfaces/routes/schemas/projects.py | Project schemas
src/routes/schemas/query.py | → | interfaces/routes/schemas/query.py | QueryRequest / QueryResponse


### 2.13 — Workers (Celery — NEW, not in spec)
The Celery worker system is entirely absent from the original spec. It decouples document ingestion from the API request cycle. Two tasks exist: ingest_task (chunking + storage) and embed_task (vectorization). Three domain-aware chunkers handle different document types.

Old Path (Actual) |  | New Path (Document) | Notes
src/workers/celery_app.py | → | workers/celery_app.py | NEW — Celery broker + backend config
src/workers/worker_settings.py | → | workers/worker_settings.py | NEW — concurrency, queues, timeouts
src/workers/tasks/ingest_task.py | → | workers/tasks/ingest_task.py | NEW — chunk + store document
src/workers/tasks/embed_task.py | → | workers/tasks/embed_task.py | NEW — vectorize + store in Milvus
src/workers/chunkers/base_chunker.py | → | workers/chunkers/base_chunker.py | NEW — ABC for all chunkers
src/workers/chunkers/chunker_factory.py | → | workers/chunkers/chunker_factory.py | NEW — selects chunker by doc type
src/workers/chunkers/sop_chunker.py | → | workers/chunkers/sop_chunker.py | NEW — Standard Operating Procedure docs
src/workers/chunkers/bpmn_chunker.py | → | workers/chunkers/bpmn_chunker.py | NEW — BPMN process documents
src/workers/chunkers/tax_circular_chunker.py | → | workers/chunkers/tax_circular_chunker.py | NEW — Algerian tax circulars


### 2.14 — Tests
Old Path (Actual) |  | New Path (Document) | Notes
src/tests/test_phase1_system_breakers.py | → | tests/unit/test_system_breakers.py | System-level exception tests
src/tests/test_phase1_erp_exceptions.py | → | tests/unit/test_erp_exceptions.py | ERP domain exception tests
src/tests/test_tenant_project_isolation.py | → | tests/integration/test_tenant_isolation.py | Tenant isolation — CRITICAL
src/tests/test_phase3_async_concurrency.py | → | tests/integration/test_async_concurrency.py | Async/Celery concurrency tests
src/tests/test_inference_backend_factory.py | → | tests/unit/test_inference_backend_factory.py | Model selector tests


## 3. SQL Pipeline — 3-Stage Architecture
This is the most important structural difference between the spec and the actual code. The spec described a two-step flow (generate → execute). The actual codebase implements a three-stage pipeline where the validation step produces a structured ValidationReport before any execution occurs. This is safer: execution only happens after an explicit validation gate.

### 3.1 — 3-Stage Pipeline Flow
Natural Language Query (masked by PIIMiddleware)
│
▼
┌──────────────────────────────────────────────────────┐
│  STAGE 1: query_generator.py                         │
│  Port:  sql_generator_port.py                        │
│  Input: {query, schema_context, tenant_id, role}     │
│  Output: SQLGenerationResult {sql: str, confidence}  │
│  LLM call (OpenAI / vLLM) — JSON mode               │
└──────────────────────┬───────────────────────────────┘
│  SQLGenerationResult
▼
┌──────────────────────────────────────────────────────┐
│  STAGE 2: query_validator.py                         │
│  Port:  sql_validator_port.py                        │
│  Input: SQLGenerationResult                          │
│  Output: ValidationReport {                          │
│    is_valid: bool,                                   │
│    errors: List[str],           ← sqlglot errors     │
│    warnings: List[str],                              │
│    has_tenant_filter: bool,     ← CRITICAL check     │
│    is_select_only: bool,        ← no DDL/DML         │
│    allowed_tables_only: bool,   ← schema whitelist   │
│    sanitized_sql: str           ← safe version       │
│  }                                                   │
│  NO LLM call — pure code validation                  │
└──────────────────────┬───────────────────────────────┘
│  ValidationReport
│  (only if is_valid == True)
▼
┌──────────────────────────────────────────────────────┐
│  STAGE 3: query_executor.py                          │
│  Port:  sql_executor_port.py                         │
│  Input: ValidationReport (sanitized_sql)             │
│  Output: ExecutionResult {                           │
│    rows: List[Dict],                                 │
│    row_count: int,                                   │
│    execution_time_ms: float,                         │
│    query_id: str,               ← for audit log      │
│    error: Optional[str]                              │
│  }                                                   │
│  asyncpg — read-only PostgreSQL ERP connection       │
└──────────────────────────────────────────────────────┘
│  ExecutionResult
▼
Answer Formatter → Response

### 3.2 — ValidationReport Domain Model
The ValidationReport is defined in src/domain/models/sql_pipeline.py. It is the contract between Stage 2 and Stage 3. Stage 3 will only accept a report where is_valid is True and has_tenant_filter is True.
# src/domain/models/sql_pipeline.py
from pydantic import BaseModel
from typing import List, Optional
class SQLGenerationResult(BaseModel):
sql: str
confidence: float
target_schemas: List[str]
generation_time_ms: float
class ValidationReport(BaseModel):
is_valid: bool
errors: List[str]
warnings: List[str]
has_tenant_filter: bool      # MUST be True — enforced by executor
is_select_only: bool         # MUST be True — enforced by executor
allowed_tables_only: bool    # MUST be True — enforced by executor
sanitized_sql: str           # sqlglot-formatted, safe SQL
original_sql: str            # for audit trail
class ExecutionResult(BaseModel):
rows: List[dict]
row_count: int
execution_time_ms: float
query_id: str                # UUID — logged to mongo_query_log
error: Optional[str] = None

### 3.3 — Stage 2: Validation Rules
Rule | Check | Fail Action | Where Enforced
SELECT only | sqlglot: statement type == SELECT | is_valid=False, error added | query_validator.py Stage 2
tenant_id filter | regex: WHERE clause contains tenant_id= | is_valid=False — CRITICAL | query_validator.py Stage 2
Table whitelist | All FROM/JOIN tables in allowed_tables set | is_valid=False, tables listed | query_validator.py Stage 2
SQL syntax | sqlglot parse — no exception | is_valid=False, error added | query_validator.py Stage 2
Double-check gate | Executor checks is_valid before executing | ValueError raised | query_executor.py Stage 3


## 4. Updated System Architecture (Actual Code)
This diagram reflects the actual codebase, not the spec. Key changes: Celery workers for async ingestion, MongoDB as the primary database, vLLM as an alternative to OpenAI, and the three-stage SQL pipeline.
┌─────────────────────────────────────────────────────────────────┐
│                   BUSINESS USER (HTTP)                          │
└────────────────────────────┬────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────┐
│               MIDDLEWARE STACK (src/middleware/)                 │
│  LoggingMW → AuthMW → RateLimitMW → RBACMW → PIIMaskingMW      │
└────────────────────────────┬────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────┐
│           ROUTES (src/routes/)                                  │
│  auth.py  data.py  projects.py  query.py  admin.py  base.py    │
└───┬──────────────────┬───────────────────────────────┬──────────┘
│                  │                               │
▼                  ▼                               ▼
┌────────┐  ┌────────────────────────────┐  ┌──────────────────┐
│USE CASES│  │   QUERY PIPELINE           │  │ CELERY WORKERS   │
│auth_user│  │                            │  │ ingest_task.py   │
│create_  │  │  query_classifier.py       │  │ embed_task.py    │
│project  │  │     ↓                      │  │ chunker_factory  │
│upload_  │  │  rag | sql | hybrid |block │  │ sop/bpmn/tax     │
│asset    │  │     ↓          ↓           │  └──────────────────┘
│process_ │  │  RAG Agent  SQL Pipeline   │
│asset    │  │             ↓              │
└─────────┘  │  generator→validator→exec  │
└────────────────────────────┘
│
┌───────────────────┴────────────────────┐
▼                                        ▼
┌────────────────────┐               ┌────────────────────────┐
│  MongoDB           │               │  Milvus (Vectors)      │
│  - projects        │               │  - chunk embeddings    │
│  - assets          │               │  - ANN search          │
│  - chunks          │               └────────────────────────┘
│  - users           │
│  - query_log       │               ┌────────────────────────┐
│  - audit_events    │               │  ERP PostgreSQL         │
└────────────────────┘               │  (read-only — asyncpg) │
│  mdm/pim/oms schemas   │
└────────────────────────┘

### 4.1 — Middleware Stack (Actual Order)
Position | File | Function | Spec Status
1 | LoggingMiddleware.py | trace_id + structured JSON logs | In spec
2 | AuthMiddleware.py | JWT RS256 validate + UserContext | In spec
3 | RateLimitMiddleware.py | Request throttling per user/IP | NEW — not in spec
4 | RBACMiddleware.py | Role permission + module access | In spec (merged ModuleAccessGuard)
5 | PIIMaskingMiddleware.py | PII detect + mask query text | In spec

ModuleAccessGuard from the spec is NOT a separate middleware file. Its logic — filtering allowed SQL tables and RAG document collections by ERP module — is embedded inside RBACMiddleware.py using erp_rbac_policy.py.


## 5. Gaps — Spec Items Not Yet in Actual Code
These items appear in the engineering specification but have no corresponding file in the actual codebase. They represent implementation gaps to address.
Spec Item | File Expected | Priority | Notes
Prometheus metrics export | observability/prometheus_metrics.py | HIGH | No metrics endpoint found — add prometheus-client
Evaluation benchmarks | evaluation/benchmarks/sql_benchmark.py | HIGH | No benchmark harness found
Hallucination scorer | evaluation/metrics/hallucination_scorer.py | HIGH | No LLM-as-judge evaluator
Hybrid agent | agents/hybrid_agent.py | MEDIUM | answer_query.py may handle it — confirm
Separate agents/ folder | agents/query_router.py etc. | LOW | Logic is in use_cases/ and infrastructure/nlp/ — structural preference only


### 5.1 — Things Only in Code (not in spec)
Actual File | What it does | Should be in spec
RateLimitMiddleware.py | Per-user/IP request throttling | Yes — add to middleware spec
workers/celery_app.py | Celery broker config for async processing | Yes — spec async processing section
workers/chunkers/* | Domain-aware chunkers (SOP, BPMN, tax circular) | Yes — spec chunker factory section
noop_embedding_provider.py | No-op embedder for testing without GPU | Yes — spec test strategy
vllm_llm_client.py | Self-hosted vLLM as LLM backend | Yes — add to tech stack
language_detection_service.py | AR/FR/EN detection for bilingual queries | Yes — ERP is bilingual
degraded_mode_service.py | Fallback behavior when LLM is unreachable | Yes — reliability section
model_selector.py | Dynamic OpenAI vs vLLM selection | Yes — model routing
di/container.py | DI wiring of all ports to implementations | Yes — add DI section
mongo_audit_log.py | Structured audit event storage | Yes — audit/compliance
minio_asset_storage.py | MinIO S3-compatible file storage | Yes — storage options
kaggle_embedding_server.ipynb | External embedding server on Kaggle GPU | Yes — deployment note
kaggle_llm_server.ipynb | External LLM server on Kaggle GPU | Yes — deployment note


## 6. Reconciled Target Folder Structure
This is the recommended folder structure that reconciles both the spec and the actual codebase. It follows Clean Architecture with the additions discovered in the code.
erp_rag/                                     # → maps to src/
├── domain/                                  # → src/domain/
│   ├── models/
│   │   ├── erp/                             # → src/domain/models/erp/
│   │   │   ├── mdm_sku.py                   # Sku.py
│   │   │   ├── mdm_supplier.py              # Supplier.py
│   │   │   ├── mdm_tax_rule.py              # TaxRule.py
│   │   │   ├── mdm_wilaya.py                # Wilaya.py
│   │   │   ├── mdm_bin.py                   # Bin.py
│   │   │   ├── pim_product.py               # Product.py
│   │   │   ├── pim_variant.py               # Variant.py
│   │   │   ├── oms_order.py                 # Order.py
│   │   │   └── crm_customer.py              # Customer.py
│   │   ├── sql_pipeline.py                  # NEW: SQLGenerationResult|ValidationReport|ExecutionResult
│   │   ├── query_log.py                     # NEW: query audit model
│   │   ├── pii_entity.py                    # NEW
│   │   ├── audit_events.py                  # NEW
│   │   └── user.py                          # NEW
│   └── ports/                               # → src/domain/ports/
│       ├── sql_generator_port.py            # Stage 1
│       ├── sql_validator_port.py            # Stage 2 — returns ValidationReport
│       ├── sql_executor_port.py             # Stage 3 — takes ValidationReport
│       ├── job_dispatcher_port.py           # NEW: Celery dispatch
│       └── ...                              # (all other ports as before)
├── application/use_cases/                   # → src/application/use_cases/
│   ├── answer_query.py                      # routes to rag|sql|hybrid|blocked
│   ├── process_asset.py                     # triggers Celery ingest_task
│   └── ...                                  # (other use cases unchanged)
├── infrastructure/
│   ├── erp/                                 # → src/infrastructure/erp/  ← SQL PIPELINE
│   │   ├── query_generator.py               # Stage 1
│   │   ├── query_validator.py               # Stage 2 → ValidationReport
│   │   ├── query_executor.py                # Stage 3 → ExecutionResult
│   │   └── erp_rbac_policy.py               # ERP module whitelist
│   ├── persistence/                         # → src/infrastructure/persistence/
│   │   ├── mongo_*.py                       # MongoDB (not PostgreSQL)
│   │   └── milvus_vector_store.py
│   ├── nlp/                                 # → src/infrastructure/nlp/
│   │   ├── openai_llm_client.py
│   │   ├── vllm_llm_client.py               # NEW: self-hosted LLM
│   │   ├── language_detection_service.py    # NEW: bilingual support
│   │   └── ...                              # (all NLP services)
│   ├── generation/                          # → src/infrastructure/generation/
│   │   ├── model_selector.py                # NEW: OpenAI vs vLLM
│   │   └── degraded_mode_service.py         # NEW: LLM fallback
│   ├── di/                                  # NEW: → src/infrastructure/di/
│   │   ├── container.py
│   │   └── factory.py
│   ├── security/                            # → src/infrastructure/security/
│   └── storage/                             # → src/infrastructure/storage/
│       ├── local_asset_storage.py
│       └── minio_asset_storage.py           # NEW: MinIO
├── interfaces/
│   ├── middleware/                          # → src/middleware/
│   │   ├── logging_middleware.py            # LoggingMiddleware.py
│   │   ├── auth_middleware.py               # AuthMiddleware.py
│   │   ├── rate_limit_middleware.py         # NEW: RateLimitMiddleware.py
│   │   ├── rbac_middleware.py               # RBACMiddleware.py (+ module guard)
│   │   └── pii_middleware.py                # PIIMaskingMiddleware.py
│   └── routes/                              # → src/routes/
│       ├── auth.py  data.py  projects.py
│       ├── query.py (→ erp_query.py)
│       └── admin.py  base.py
├── workers/                                 # NEW: → src/workers/
│   ├── celery_app.py
│   ├── tasks/
│   │   ├── ingest_task.py
│   │   └── embed_task.py
│   └── chunkers/
│       ├── chunker_factory.py
│       ├── sop_chunker.py
│       ├── bpmn_chunker.py
│       └── tax_circular_chunker.py
├── observability/                           # GAP: needs creation
│   ├── prometheus_metrics.py                # NOT YET IMPLEMENTED
│   └── structured_logger.py
├── evaluation/                              # GAP: needs creation
│   ├── benchmarks/sql_benchmark.py
│   └── metrics/hallucination_scorer.py
└── tests/                                   # → src/tests/
├── unit/
└── integration/

## 7. Quick Reference — Key Decisions
Decision | Spec Said | Actual Code Does | Action
Primary DB | PostgreSQL 17 | MongoDB (motor) | Keep MongoDB for RAG state; PG only for ERP SQL
SQL Pipeline | Generate → Execute | Generate → Validate → Execute (3 stages) | Document the 3-stage model (this doc)
LLM Backend | OpenAI GPT-4o only | OpenAI + vLLM (switchable) | Keep model_selector.py — add to spec
Async Processing | Synchronous | Celery workers | Keep Celery — add worker section to spec
Chunking | RecursiveCharacter | Factory: SOP/BPMN/TaxCircular | Keep factory — richer for ERP docs
Module Guard | Separate middleware | Embedded in RBACMiddleware | Keep embedded — simpler, same effect
Rate Limiting | Not specified | RateLimitMiddleware.py | Keep — add to spec
Observability | Prometheus defined | Not yet implemented | IMPLEMENT — prometheus-client + /metrics route
Evaluation | Benchmarks defined | Not yet implemented | IMPLEMENT — sql_benchmark.py + hallucination_scorer.py
File Storage | Local only | Local + MinIO | Keep MinIO — production-ready


---
## CRITICAL FACTS (Architecture Mapping)

1. **MongoDB** is the primary RAG store — NOT PostgreSQL
   - PostgreSQL is ERP read-only target only (via query_executor.py)
2. **SQL pipeline is 3 stages** — never collapse to 2:
   - Stage 1: query_generator.py → SQLGenerationResult
   - Stage 2: query_validator.py → ValidationReport (NO LLM call, pure code)
   - Stage 3: query_executor.py → ExecutionResult (only if is_valid=True AND has_tenant_filter=True)
3. **ModuleAccessGuard** is embedded in RBACMiddleware — NOT a separate file
4. **Middleware order**: Logging → Auth → RateLimit → RBAC → PIIMasking
5. **Two missing modules** to create: observability/ and evaluation/
6. **Celery workers** handle async ingestion — not in spec but in code
7. **vLLM** is a fallback to OpenAI — both clients exist
8. **MinIO** is production file storage — local is dev only
9. **Domain enums** (`UserRole`, `QueryIntent`, `ChunkStrategy`, `ErpModule`) are canonical in `src/domain/enums.py` — never hard-code role strings anywhere else (see Section 8)
---

---

## 8. Domain Conventions — Canonical Enums & Permission Matrix

These are the **authoritative definitions** for all role, intent, and chunking constants
used across the codebase. Any file that references these values MUST import from
`src/domain/enums.py`. Hard-coded strings are forbidden.

**Canonical file:** `src/domain/enums.py`

---

### 8.1 — UserRole

The nine ERP personas that can hold a JWT. Replace the old placeholder roles
(ADMIN / MANAGER / ANALYST / VIEWER) everywhere.

| Constant | Value | Description |
|---|---|---|
| `UserRole.SUPER_ADMIN` | `"SUPER_ADMIN"` | Full system access — all modules, all operations |
| `UserRole.PRODUCT_MANAGER` | `"PRODUCT_MANAGER"` | Inventory, procurement, CRM — SQL + RAG |
| `UserRole.INVENTORY_MANAGER` | `"INVENTORY_MANAGER"` | Inventory and warehouse — SQL + RAG |
| `UserRole.FINANCE_MANAGER` | `"FINANCE_MANAGER"` | Finance and reporting — SQL + RAG |
| `UserRole.WAREHOUSE_OPERATOR` | `"WAREHOUSE_OPERATOR"` | Warehouse operations — SQL + RAG; inventory RAG only |
| `UserRole.PROCUREMENT_MANAGER` | `"PROCUREMENT_MANAGER"` | Procurement and inventory — SQL + RAG; finance RAG only |
| `UserRole.CRM_AGENT` | `"CRM_AGENT"` | CRM module — SQL + RAG; reporting RAG only |
| `UserRole.LOGISTICS_AGENT` | `"LOGISTICS_AGENT"` | Logistics and warehouse — SQL + RAG; reporting RAG only |
| `UserRole.REPORTING_ANALYST` | `"REPORTING_ANALYST"` | **RAG only across all modules — zero SQL access** |

**Admin route guard:** Only `UserRole.SUPER_ADMIN` may access `/admin/*` paths.
All other roles receive 403.

---

### 8.2 — QueryIntent

Output of the query classifier (`src/infrastructure/nlp/query_classifier.py`).
Determines which pipeline branch handles the request.

| Constant | Value | Handler |
|---|---|---|
| `QueryIntent.RAG` | `"RAG"` | Vector search → context builder → LLM |
| `QueryIntent.SQL` | `"SQL"` | 3-stage SQL pipeline (generator → validator → executor) |
| `QueryIntent.HYBRID` | `"HYBRID"` | RAG + SQL in parallel, merged answer |
| `QueryIntent.BLOCKED` | `"BLOCKED"` | Request rejected — harmful or out-of-scope |

Target classifier accuracy: **≥ 92%** (Sprint 9 gate).

---

### 8.3 — ChunkStrategy

Strategy selected by `chunker_factory.py` based on document type.
Maps document MIME type / metadata tag → concrete chunker class.

| Constant | Value | Chunker file | Document type |
|---|---|---|---|
| `ChunkStrategy.RECURSIVE` | `"RECURSIVE"` | `base_chunker.py` | Generic / fallback |
| `ChunkStrategy.SENTENCE` | `"SENTENCE"` | `base_chunker.py` | Narrative prose |
| `ChunkStrategy.TOKEN` | `"TOKEN"` | `base_chunker.py` | Dense technical text |
| `ChunkStrategy.BPMN` | `"BPMN"` | `bpmn_chunker.py` | BPMN process diagrams / XML |
| `ChunkStrategy.TAX` | `"TAX"` | `tax_circular_chunker.py` | Algerian tax circulars (DGI) |
| `ChunkStrategy.SOP` | `"SOP"` | `sop_chunker.py` | Standard Operating Procedures |

---

### 8.4 — ErpModule

ERP business domains. Used as keys in `MODULE_ACCESS_MATRIX` and as the
`module` label for RBAC violation Prometheus metrics.

| Constant | Value | Typical SQL tables |
|---|---|---|
| `ErpModule.INVENTORY` | `"inventory"` | `inventory`, `products`, `returns` |
| `ErpModule.FINANCE` | `"finance"` | `invoices`, `accounts_receivable`, `vat_transactions`, `budget_actuals`, `payroll` |
| `ErpModule.WAREHOUSE` | `"warehouse"` | `shipments` |
| `ErpModule.PROCUREMENT` | `"procurement"` | `purchase_orders`, `suppliers`, `contracts` |
| `ErpModule.CRM` | `"crm"` | `customers` |
| `ErpModule.LOGISTICS` | `"logistics"` | `shipments` |
| `ErpModule.REPORTING` | `"reporting"` | `budget_actuals` (read via finance) |
| `ErpModule.ADMIN` | `"admin"` | `employees`, `users` |

---

### 8.5 — MODULE_ACCESS_MATRIX

Defined in `src/infrastructure/auth/erp_rbac_policy.py`, imported from `src/domain/enums.py`.
`ModulePermission(can_sql, can_rag)` — both booleans.

| Role | Module | can_sql | can_rag |
|---|---|---|---|
| SUPER_ADMIN | ALL | ✓ | ✓ |
| PRODUCT_MANAGER | INVENTORY | ✓ | ✓ |
| PRODUCT_MANAGER | PROCUREMENT | ✓ | ✓ |
| PRODUCT_MANAGER | CRM | ✓ | ✓ |
| PRODUCT_MANAGER | REPORTING | ✗ | ✓ |
| INVENTORY_MANAGER | INVENTORY | ✓ | ✓ |
| INVENTORY_MANAGER | WAREHOUSE | ✓ | ✓ |
| INVENTORY_MANAGER | REPORTING | ✗ | ✓ |
| FINANCE_MANAGER | FINANCE | ✓ | ✓ |
| FINANCE_MANAGER | REPORTING | ✓ | ✓ |
| WAREHOUSE_OPERATOR | WAREHOUSE | ✓ | ✓ |
| WAREHOUSE_OPERATOR | INVENTORY | ✗ | ✓ |
| PROCUREMENT_MANAGER | PROCUREMENT | ✓ | ✓ |
| PROCUREMENT_MANAGER | INVENTORY | ✓ | ✓ |
| PROCUREMENT_MANAGER | FINANCE | ✗ | ✓ |
| PROCUREMENT_MANAGER | REPORTING | ✗ | ✓ |
| CRM_AGENT | CRM | ✓ | ✓ |
| CRM_AGENT | REPORTING | ✗ | ✓ |
| LOGISTICS_AGENT | LOGISTICS | ✓ | ✓ |
| LOGISTICS_AGENT | WAREHOUSE | ✓ | ✓ |
| LOGISTICS_AGENT | REPORTING | ✗ | ✓ |
| REPORTING_ANALYST | ALL | ✗ | ✓ |

**Rules enforced in `erp_rbac_policy.py`:**
- `get_allowed_modules(role)` → `dict[ErpModule, ModulePermission]` (absent key = no access)
- `is_table_allowed(role, table_name)` → `bool` (resolves table → module, checks `can_sql`)
- `is_collection_allowed(role, collection_name)` → `bool` (resolves collection → module, checks `can_rag`)
- REPORTING_ANALYST: `is_table_allowed(...)` always returns `False`
- SUPER_ADMIN: all functions always return `True`

---

### 8.6 — Old Role Migration

| Old placeholder | New canonical role |
|---|---|
| `"ADMIN"` | `UserRole.SUPER_ADMIN` |
| `"MANAGER"` | `UserRole.PRODUCT_MANAGER` |
| `"ANALYST"` | `UserRole.REPORTING_ANALYST` |
| `"VIEWER"` | `UserRole.REPORTING_ANALYST` |

Old strings must be purged from all code, tests, and JWT fixtures.

---

# DOCUMENT 2: Sprint Plan & Git Strategy
---

ERP AGENTIC RAG
Sprint Plan & Git Strategy
10-Week Execution Plan  ·  Git Branching Model  ·  Definition of Done
Property | Value
Total Duration | 10 weeks (2.5 months)
Sprint Length | 1 week per sprint
Team Size | 1–3 engineers (adapts to available capacity)
Git Strategy | Trunk-Based Development with short-lived feature branches
Branching Model | main / develop / sprint-N / feature/XXX / hotfix/XXX
CI Trigger | Every push to any branch
CD Trigger | Merge to develop (staging) · Tag on main (production)
Definition of Done | Code + tests passing + branch merged + tag pushed
Progress Tracking | Git tag per sprint + CHANGELOG.md entry per deliverable


## 1. Plan Overview
The 10-week plan is organized around the actual codebase gaps identified in the architecture mapping document. Sprints 1–3 close the critical infrastructure gaps (observability, evaluation, DI hardening). Sprints 4–6 complete the SQL pipeline, middleware, and worker reliability. Sprints 7–9 add the remaining intelligence layer (hybrid agent, model selection, degraded mode). Sprint 10 is hardening-only: security, load testing, documentation.
RULE: Every sprint produces a deployable increment. No sprint ends with partially working code merged to develop. Features are merged only when all Definition of Done items pass.


### 1.1 — Sprint Map
Sprint | Week | Theme | Primary Deliverable | Risk
1 | Observability Foundation | Prometheus metrics + /metrics endpoint | Low
2 | Evaluation Framework | SQL benchmark + hallucination scorer + CI gate | Medium
3 | DI Hardening + Auth | DI container wired + full auth flow tested | Low
4 | SQL Pipeline Completion | 3-stage pipeline tested end-to-end with ERP PG | High
5 | Middleware Stack Hardening | Rate limiting tuned + module guard verified | Medium
6 | Worker Reliability | Celery retry/dead-letter + chunker tests | Medium
7 | Hybrid Agent | RAG+SQL parallel merge — tested on 20 queries | High
8 | Model Selection + Degraded | vLLM fallback + degraded mode tested | Medium
9 | Query Intelligence | Rewriter + classifier accuracy > 92% | Medium
10 | Hardening & Documentation | Pen test + load test + full README updated | Low


### 1.2 — Global Definition of Done (applies to every sprint)
✓ | All new code has unit tests with at least 80% line coverage
✓ | No new linting errors (ruff + mypy pass clean)
✓ | Feature branch merged to develop via Pull Request with at least one reviewer approval
✓ | Git sprint tag pushed (e.g. sprint-1-done)
✓ | CHANGELOG.md updated with deliverables for this sprint
✓ | CI pipeline green on develop after merge
✓ | No regression in existing tests (test suite must not shrink)

SPRINT 1  — Observability Foundation
📅 Week 1     🎯 Focus: Prometheus + Structured Logging


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Create observability/ module | observability/__init__.py | 0.5d | Module scaffold
2 | Implement prometheus_metrics.py — define all counters/histograms | observability/prometheus_metrics.py | 1d | All metrics defined
3 | Wire metrics into middleware (logging, auth, rbac, pii, ratelimit) | src/middleware/*.py | 1d | Metrics incremented on every request
4 | Add /metrics route to admin.py | src/routes/admin.py | 0.5d | Prometheus scrape endpoint live
5 | Implement structured_logger.py — JSON format with trace_id propagation | observability/structured_logger.py | 0.5d | All logs are valid JSON
6 | Replace all print/logging.info calls with structured logger | src/**/*.py | 1d | Zero raw prints in production code
7 | Write unit tests for metrics and logger | src/tests/unit/test_observability.py | 0.5d | Tests green
8 | Add Prometheus scrape config to docker-compose.yaml | docker/docker-compose.yaml | 0.5d | prometheus scrapes /metrics locally


#### Definition of Done
✓ | GET /metrics returns valid Prometheus text format — scraped successfully by prometheus container
✓ | Every middleware logs a JSON line with trace_id, user_id, latency_ms, status on every request
✓ | auth_failure_rate, rbac_violation_rate, pii_detection_rate, request_latency counters all increment correctly
✓ | structured_logger replaces all existing logging calls — zero raw prints
✓ | Unit tests for observability module pass — coverage >= 80%
✓ | Sprint tag sprint-1-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Create sprint branch | git checkout develop && git checkout -b sprint-1/observability
Daily commit convention | feat(observability): add prometheus_metrics.py
One feature sub-branch per task | git checkout -b feature/prometheus-metrics (from sprint-1)
Merge feature into sprint | git checkout sprint-1/observability && git merge feature/prometheus-metrics
End-of-sprint merge to develop | git checkout develop && git merge --no-ff sprint-1/observability
Tag the sprint | git tag sprint-1-done && git push origin sprint-1-done
Update CHANGELOG | echo '## Sprint 1 — Observability' >> CHANGELOG.md

SPRINT 2  — Evaluation Framework
📅 Week 2     🎯 Focus: SQL Benchmark + Hallucination Scorer + CI Gate


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Create evaluation/ module scaffold | evaluation/__init__.py | 0.5d | Module ready
2 | SQL benchmark harness: 20 test queries with expected SQL patterns | evaluation/benchmarks/sql_benchmark.py | 1.5d | Benchmark runnable
3 | Hallucination scorer: LLM-as-judge prompt + grounding score | evaluation/metrics/hallucination_scorer.py | 1d | Scorer returns 0.0–1.0
4 | RAG benchmark: 15 retrieval test cases with expected chunk IDs | evaluation/benchmarks/rag_benchmark.py | 1d | Benchmark runnable
5 | CI integration: add benchmark step to GitHub Actions | ci.yml / .github/workflows/ | 0.5d | Benchmark runs on every PR to develop
6 | Define thresholds as env vars: SQL_SUCCESS_MIN=0.95, HALLUCINATION_MAX=0.05 | helpers/config.py | 0.5d | Thresholds configurable
7 | Write tests for the benchmark harness itself | src/tests/unit/test_evaluation.py | 0.5d | Meta-tests pass


#### Definition of Done
✓ | sql_benchmark.py runs 20 queries — reports pass/fail per query and overall success_rate
✓ | CI fails the PR if sql_success_rate < 0.95 or hallucination_rate > 0.05
✓ | hallucination_scorer.py returns a grounding_score between 0.0 and 1.0 for any answer/context pair
✓ | rag_benchmark.py runs 15 retrieval cases and reports precision@5
✓ | All benchmark scripts exit with code 0 on pass, 1 on fail (CI-compatible)
✓ | Sprint tag sprint-2-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Branch from develop | git checkout -b sprint-2/evaluation develop
Benchmark test data committed | evaluation/benchmarks/data/sql_test_cases.json (committed, not gitignored)
Tag format | sprint-2-done
CI YAML snippet | python evaluation/benchmarks/sql_benchmark.py || exit 1
Never commit API keys | Use .env.test with placeholder keys — real keys in CI secrets only


#### Blockers / Dependencies
Requires access to ERP PostgreSQL test instance with seeded data — coordinate with ERP team before Sprint 2 starts
SPRINT 3  — DI Hardening + Full Auth Flow
📅 Week 3     🎯 Focus: Wiring All Ports + Auth Integration Tests


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Audit di/container.py — verify all ports have registered implementations | src/infrastructure/di/container.py | 1d | All ports mapped
2 | Add startup validation: container.validate() raises on missing binding | src/infrastructure/di/container.py | 0.5d | Missing binding = crash on startup
3 | Write integration test for full auth flow: register→login→get token→use token | src/tests/integration/test_auth_flow.py | 1d | Auth happy path green
4 | Test all auth failure cases: expired, missing, tampered, wrong algorithm | src/tests/integration/test_auth_flow.py | 0.5d | All 401 cases covered
5 | Test RBAC enforcement per role: ADMIN/MANAGER/ANALYST/VIEWER | src/tests/integration/test_rbac.py | 0.5d | Each role tested on each route
6 | Add password reset flow if missing | src/routes/auth.py + use_cases/auth_user.py | 0.5d | Reset endpoint works
7 | Validate DI factory creates use case instances with correct dependencies | src/tests/unit/test_di_factory.py | 0.5d | Factory tests pass
8 | Document all registered bindings in ARCHITECTURE.md | ARCHITECTURE.md | 0.5d | Bindings documented


#### Definition of Done
✓ | container.validate() called at startup — app refuses to start with missing port binding
✓ | Full auth integration test: POST /auth/login returns JWT → POST /api/erp/query with JWT → 200
✓ | All 4 RBAC roles tested: each role only accesses permitted routes (403 on others)
✓ | All token failure cases return 401 with clear error message
✓ | DI factory unit test: use case constructed with mocked dependencies — no real DB needed
✓ | Sprint tag sprint-3-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Branch | git checkout -b sprint-3/di-auth develop
Integration test tag | git tag sprint-3-done
Auth test fixtures | src/tests/fixtures/jwt_fixtures.py — generate test tokens without hitting real IdP

SPRINT 4  — SQL Pipeline End-to-End
📅 Week 4     🎯 Focus: 3-Stage Pipeline Fully Tested Against ERP PostgreSQL


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Integration test: Stage 1 generator produces valid SQL for 10 NL queries | src/tests/integration/test_sql_generator.py | 1d | Stage 1 tested
2 | Unit test: Stage 2 validator — all validation rules with edge cases | src/tests/unit/test_sql_validator.py | 1d | 18+ test cases
3 | Integration test: Stage 2 catches missing tenant_id — raises before Stage 3 | src/tests/integration/test_sql_pipeline.py | 0.5d | Tenant guard tested
4 | Integration test: Stage 3 executor — executes sanitized SQL, returns ExecutionResult | src/tests/integration/test_sql_executor.py | 1d | Stage 3 tested
5 | End-to-end test: NL query → ValidationReport → ExecutionResult → formatted answer | src/tests/integration/test_sql_e2e.py | 1d | Full pipeline tested
6 | Add query_id to ExecutionResult and log to mongo_query_log_repository | src/infrastructure/erp/query_executor.py | 0.5d | Every execution logged
7 | Add SQL pipeline metrics to prometheus_metrics.py | observability/prometheus_metrics.py | 0.5d | sql_pipeline_* metrics exported


#### Definition of Done
✓ | sql_benchmark.py passes with >= 95% success rate against ERP test database
✓ | ValidationReport.has_tenant_filter=False causes executor to raise ValueError — never executes
✓ | All non-SELECT SQL (INSERT/UPDATE/DROP/DDL) caught by validator — Stage 3 never reached
✓ | Every ExecutionResult has a unique query_id stored in MongoDB query_log collection
✓ | SQL pipeline metrics visible in Prometheus: sql_stage1_latency, sql_stage2_errors, sql_stage3_rows
✓ | Sprint tag sprint-4-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Branch | git checkout -b sprint-4/sql-pipeline develop
ERP test DB config | src/tests/fixtures/.env.test — PG_HOST=localhost, PG_DATABASE=erp_test
Seed script | src/tests/fixtures/seed_erp_test.sql — committed to repo for reproducibility
Tag | sprint-4-done


#### Blockers / Dependencies
ERP PostgreSQL test instance must be accessible — if not available, use seed_erp_test.sql in Docker
SPRINT 5  — Middleware Stack Hardening
📅 Week 5     🎯 Focus: Rate Limiting Tuned + ModuleGuard Verified + PII Accuracy


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Rate limit tests: per-user throttle, per-IP throttle, burst handling | src/tests/integration/test_rate_limit.py | 1d | Rate limit tests pass
2 | Module guard tests: verify SQL table filtering per ERP module | src/tests/integration/test_module_guard.py | 1d | Module isolation verified
3 | PII accuracy test: 30 queries with embedded PII — verify mask rate | src/tests/unit/test_pii_masking.py | 0.5d | PII detection >= 98% recall
4 | Add Algerian NID (18-digit) and tax ID (15-digit) to PII patterns if missing | src/middleware/PIIMaskingMiddleware.py | 0.5d | DZ-specific PII detected
5 | Middleware latency test: full stack overhead < 20ms per request | src/tests/performance/test_middleware_latency.py | 0.5d | Latency budget confirmed
6 | Add middleware_violations metric to Prometheus for each middleware | observability/prometheus_metrics.py | 0.5d | Violations visible
7 | Integration test: request rejected at AuthMW never reaches SQL pipeline | src/tests/integration/test_middleware_order.py | 0.5d | Order enforced
8 | Review and document RBACMiddleware + erp_rbac_policy.py decision matrix | ARCHITECTURE.md | 0.5d | Matrix documented


#### Definition of Done
✓ | Rate limiting: 60 req/min per user, 200 req/min per IP — verified by integration test
✓ | ANALYST role cannot query finance_schema — ModuleGuard returns 403 verified by test
✓ | PII masking detects email, phone (DZ format), NID (18-digit), taxId (15-digit) — >= 98% recall on test set
✓ | Full middleware stack (5 layers) adds < 20ms overhead on a local test request
✓ | auth_failure_rate, rbac_violation_rate, pii_detection_rate all visible in Prometheus
✓ | Sprint tag sprint-5-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Branch | git checkout -b sprint-5/middleware-hardening develop
PII test data file | src/tests/fixtures/pii_test_queries.json — 30 queries with ground-truth labels
Tag | sprint-5-done

SPRINT 6  — Worker Reliability
📅 Week 6     🎯 Focus: Celery Retry + Dead-Letter + Chunker Factory Tests


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Celery retry policy test: ingest_task retries 3× on failure then dead-letter | src/tests/integration/test_celery_tasks.py | 1d | Retry policy verified
2 | Dead-letter queue: failed tasks written to MongoDB failed_tasks collection | src/workers/tasks/ingest_task.py | 0.5d | Dead-letter implemented
3 | Chunker factory unit tests: SOP / BPMN / tax_circular — each produces correct chunks | src/tests/unit/test_chunker_factory.py | 1d | All chunkers tested
4 | Chunker edge cases: empty document, single-page, > 500 pages | src/tests/unit/test_chunker_factory.py | 0.5d | Edge cases handled
5 | embed_task idempotency: re-embedding same file_id does not create duplicates | src/tests/integration/test_embed_task.py | 0.5d | Idempotent embedding
6 | Worker metrics: tasks_dispatched, tasks_failed, task_duration_ms | observability/prometheus_metrics.py | 0.5d | Worker metrics exported
7 | Add job status polling endpoint to admin.py: GET /admin/jobs/{job_id} | src/routes/admin.py | 0.5d | Job status readable
8 | Document worker architecture and retry policy in ARCHITECTURE.md | ARCHITECTURE.md | 0.5d | Workers documented


#### Definition of Done
✓ | ingest_task retries exactly 3 times with exponential backoff then writes to failed_tasks — verified by test
✓ | SOP chunker, BPMN chunker, tax_circular chunker each produce expected chunk count on test documents
✓ | Re-running embed_task for same file_id does not create duplicate vectors in Milvus
✓ | GET /admin/jobs/{job_id} returns {status: pending|running|done|failed, result, error}
✓ | Celery worker metrics visible in Prometheus
✓ | Sprint tag sprint-6-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Branch | git checkout -b sprint-6/worker-reliability develop
Test documents committed | src/tests/fixtures/documents/ — one SOP PDF, one BPMN XML, one tax circular TXT
Celery test config | Use CELERY_TASK_ALWAYS_EAGER=True in test environment for synchronous execution
Tag | sprint-6-done

SPRINT 7  — Hybrid Agent
📅 Week 7     🎯 Focus: RAG + SQL Parallel Merge Tested on 20 Queries


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Implement hybrid_agent.py using asyncio.gather for parallel RAG+SQL | src/application/use_cases/answer_query.py or agents/ | 1.5d | Hybrid path implemented
2 | Synthesis prompt: merge SQL data + RAG context into coherent answer | src/infrastructure/generation/prompt_service.py | 0.5d | Synthesis prompt tested
3 | Hybrid decision logic: classifier returns 'hybrid' → both agents fire | src/infrastructure/nlp/query_classifier.py | 0.5d | Hybrid routing works
4 | Integration test: 20 hybrid queries — verify both SQL + RAG results merged | src/tests/integration/test_hybrid_agent.py | 1d | 20 queries pass
5 | Latency test: hybrid path must complete < 8s p95 | src/tests/performance/test_hybrid_latency.py | 0.5d | Latency budget met
6 | Add hybrid_query metrics: hybrid_success_rate, hybrid_latency_ms | observability/prometheus_metrics.py | 0.5d | Hybrid metrics exported
7 | Handle partial failure: if SQL fails, return RAG only (and vice versa) | agents/hybrid_agent.py | 0.5d | Graceful degradation


#### Definition of Done
✓ | asyncio.gather fires SQL agent and RAG agent simultaneously — not sequentially
✓ | Synthesis LLM call merges SQL rows and RAG chunks into a single coherent answer
✓ | If SQL stage fails validation, hybrid agent falls back to RAG-only (not 500 error)
✓ | 20 hybrid test queries all return answers with both sql_source and rag_source cited
✓ | Hybrid path p95 latency < 8 seconds in integration test
✓ | Sprint tag sprint-7-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Branch | git checkout -b sprint-7/hybrid-agent develop
Hybrid test queries | src/tests/fixtures/hybrid_test_queries.json — 20 queries requiring both SQL + docs
Tag | sprint-7-done


#### Blockers / Dependencies
Requires Sprint 4 (SQL pipeline) and Sprint 3 (RAG agent) to be fully merged to develop
SPRINT 8  — Model Selection + Degraded Mode
📅 Week 8     🎯 Focus: vLLM Fallback + Graceful Degradation Under LLM Failure


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Model selector tests: OpenAI → vLLM fallback on connection failure | src/tests/unit/test_model_selector.py | 1d | Fallback tested
2 | Degraded mode: if all LLMs fail, return cached answer or 'service degraded' | src/infrastructure/generation/degraded_mode_service.py | 1d | Degraded mode implemented
3 | Circuit breaker: after 5 consecutive LLM failures, open circuit for 60s | src/infrastructure/generation/model_selector.py | 0.5d | Circuit breaker works
4 | Degraded mode integration test: mock OpenAI + vLLM both return 503 | src/tests/integration/test_degraded_mode.py | 0.5d | Degraded response returned
5 | Cache layer: store last successful answer per query hash for degraded fallback | src/infrastructure/generation/degraded_mode_service.py | 0.5d | Cache fallback works
6 | Metrics: llm_failure_rate, circuit_breaker_state, degraded_mode_activations | observability/prometheus_metrics.py | 0.5d | LLM health metrics exported
7 | Kaggle notebook integration: document how to start external LLM/embedding servers | notebooks/kaggle_llm_server.ipynb + ARCHITECTURE.md | 0.5d | Notebook documented


#### Definition of Done
✓ | model_selector falls back to vLLM when OpenAI returns 5xx — verified by mocked test
✓ | When all LLMs fail: system returns HTTP 503 with {degraded: true, cached_answer: ...} — not a 500
✓ | Circuit breaker opens after 5 failures and stays open for 60s — verified by integration test
✓ | llm_failure_rate metric increments on every LLM failure — visible in Prometheus
✓ | Kaggle notebook startup documented: URL injected via EMBEDDING_SERVER_URL env var
✓ | Sprint tag sprint-8-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Branch | git checkout -b sprint-8/model-selection develop
Mock LLM in tests | Use pytest monkeypatch to mock openai.ChatCompletion.create → raises ConnectionError
Tag | sprint-8-done

SPRINT 9  — Query Intelligence
📅 Week 9     🎯 Focus: Classifier Accuracy > 92% + Query Rewriter + Language Detection


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Classifier accuracy benchmark: 50 queries labeled rag|sql|hybrid|blocked | evaluation/benchmarks/classifier_benchmark.py | 1d | Benchmark defined
2 | Run benchmark — if accuracy < 92%, tune classifier prompt | src/infrastructure/nlp/query_classifier.py + src/infrastructure/generation/prompt_service.py | 1d | Accuracy >= 92%
3 | Query rewriter tests: 15 ambiguous queries — verify rewritten form is clearer | src/tests/unit/test_query_rewriter.py | 0.5d | Rewriter tested
4 | Language detection tests: Arabic / French / English queries classified correctly | src/tests/unit/test_language_detection.py | 0.5d | Language detection >= 95%
5 | Add language to QueryRequest and use it in prompt selection | src/routes/schemas/query.py + prompt_service.py | 0.5d | Bilingual prompts work
6 | Blocked classifier: test 10 harmful / out-of-scope queries return 'blocked' | src/tests/unit/test_query_classifier_blocked.py | 0.5d | Blocked queries caught
7 | Add classifier metrics: classification_accuracy (from benchmark), blocked_rate | observability/prometheus_metrics.py | 0.5d | Classifier metrics exported
8 | Update evaluation CI gate with classifier benchmark | ci.yml | 0.5d | CI checks classifier accuracy


#### Definition of Done
✓ | classifier_benchmark.py runs 50 labeled queries — reports per-class accuracy and overall accuracy
✓ | Overall classifier accuracy >= 92% — CI fails if below threshold
✓ | Arabic queries routed correctly (language detected as 'ar', Arabic prompt used)
✓ | 10 harmful/out-of-scope queries all return decision='blocked' with reason
✓ | Query rewriter produces semantically equivalent but unambiguous reformulation for 15 test cases
✓ | Sprint tag sprint-9-done pushed, CHANGELOG updated


#### Git Work This Sprint
Action | Command / Detail
Branch | git checkout -b sprint-9/query-intelligence develop
Classifier test data | evaluation/benchmarks/data/classifier_test_cases.json — 50 labeled queries
Bilingual test cases | Include 15 Arabic queries and 15 French queries in test set
Tag | sprint-9-done

SPRINT 10  — Hardening & Documentation
📅 Week 10     🎯 Focus: Pen Test + Load Test + Full Docs + v1.0.0 Release


#### Tasks & Deliverables
# | Task | Files Touched | Effort | Output
1 | Penetration test: SQL injection via query text — verify validator blocks all | src/tests/security/test_sql_injection.py | 1d | Zero injections succeed
2 | Cross-tenant test: verify no query returns another tenant's data | src/tests/security/test_tenant_isolation.py | 0.5d | Zero leakage
3 | Load test: 50 concurrent users, p95 < 3s, p99 < 8s | src/tests/performance/locustfile.py | 1d | Latency budgets met
4 | Update README.md — full setup, env vars, docker-compose, run instructions | README.md | 0.5d | README complete
5 | Write ARCHITECTURE.md final version — reflects actual running system | ARCHITECTURE.md | 0.5d | Architecture documented
6 | OpenAPI spec review — all routes documented with request/response examples | src/main.py + route docstrings | 0.5d | Swagger UI complete
7 | Final CHANGELOG review — all sprints accounted for | CHANGELOG.md | 0.5d | Changelog complete
8 | Create v1.0.0 release tag — merge develop → main | Git | 0.5d | v1.0.0 tag on main


#### Definition of Done
✓ | 100 SQL injection attempt queries — zero bypass the 3-stage validation pipeline
✓ | Cross-tenant isolation test: authenticated as tenant_A, cannot retrieve tenant_B data under any query
✓ | Load test at 50 concurrent users: p95 < 3s, p99 < 8s, zero 5xx responses
✓ | README.md covers: prerequisites, installation, .env setup, docker-compose up, run server, run tests
✓ | ARCHITECTURE.md fully up to date — matches actual running code
✓ | v1.0.0 git tag created on main — CHANGELOG entry complete
✓ | All 10 sprint tags visible in git log: sprint-1-done through sprint-10-done


#### Git Work This Sprint
Action | Command / Detail
Load test branch | git checkout -b sprint-10/hardening develop
Security test suite | src/tests/security/ — separate directory, not run in unit CI (run in security CI job)
Final merge to main | git checkout main && git merge --no-ff develop && git tag v1.0.0
Push release | git push origin main && git push origin v1.0.0
GitHub Release | Create GitHub Release from v1.0.0 tag — attach CHANGELOG section as release notes


## 3. Git Strategy
The git strategy is designed for a small team (1–3 engineers) working on a single codebase. It prioritises visibility of progress via tags, keeps the main branch always deployable, and uses branch names that directly map to sprint work so progress is self-documenting.
CORE PRINCIPLE: Every deliverable has a git event. Sprints start with a branch. Features create sub-branches. Sprints end with a merge + tag. Releases merge develop to main + semantic version tag. The git log IS the project history.


### 3.1 — Branch Hierarchy
main                            ← production — only receives merges from develop via PR
│                                   only tagged here: v1.0.0, v1.1.0, v1.0.1
│
└── develop                     ← integration — all sprints merge here
│                               CI runs on every push
│                               Staging deployment on every merge
│
├── sprint-1/observability   ← one branch per sprint
│   ├── feature/prometheus-metrics
│   ├── feature/structured-logger
│   └── feature/metrics-middleware-wiring
│
├── sprint-2/evaluation
│   ├── feature/sql-benchmark
│   └── feature/hallucination-scorer
│
├── sprint-N/theme          ← pattern repeats for all 10 sprints
│   └── feature/specific-task
│
├── hotfix/critical-bug     ← from develop, merged back to develop + main
└── experiment/prompt-v2    ← never merges to develop — throwaway exploration

### 3.2 — Branch Naming Convention
Branch Type | Pattern | Example | Lifetime
Sprint branch | sprint-N/theme | sprint-4/sql-pipeline | 1 week — deleted after merge
Feature branch | feature/short-description | feature/prometheus-metrics | 1–3 days — deleted after merge to sprint
Bug fix branch | fix/short-description | fix/pii-phone-pattern | Hours — deleted after merge
Hotfix branch | hotfix/short-description | hotfix/tenant-filter-bypass | < 4 hours — CRITICAL — merged to both develop + main
Experiment branch | experiment/short-desc | experiment/vllm-qwen-model | Indefinite — NEVER merges to develop
Release branch | release/vX.Y.Z | release/v1.0.0 | Only if complex release prep needed — optional


### 3.3 — Commit Message Convention
All commits follow Conventional Commits (conventionalcommits.org). This enables automatic CHANGELOG generation and semantic version bumping.
Format:  <type>(<scope>): <subject>
Types:
feat     — new feature
fix      — bug fix
test     — adding or updating tests
refactor — code change, no feature/fix
docs     — documentation only
chore    — build, CI, dependencies
perf     — performance improvement
security — security fix (use with extra care)
Examples:
feat(observability): add prometheus_metrics.py with request counters
feat(sql-pipeline): implement ValidationReport in Stage 2 validator
fix(pii): add Algerian NID 18-digit pattern to PIIMaskingMiddleware
test(sql): add 20-query benchmark harness for sql_benchmark.py
test(tenant): add cross-tenant isolation integration test
chore(ci): add classifier benchmark gate to GitHub Actions
docs(architecture): update ARCHITECTURE.md with DI container bindings
security(sql): harden executor to reject ValidationReport with is_valid=False
NEVER:
fix stuff          ← too vague
WIP                ← do not push WIP to sprint branch, only to feature branch
updated files      ← meaningless
temp commit        ← clean up before merging feature → sprint

### 3.4 — Tag Strategy
Tag | Pattern | When Created | Meaning
Sprint done | sprint-N-done | End of every sprint — after merge to develop | Snapshot of integrate state at sprint boundary
Sprint start | sprint-N-start | First commit on sprint branch (optional) | Baseline for sprint diff: git diff sprint-3-start sprint-3-done
Release | vMAJOR.MINOR.PATCH | Merge develop → main | Production-ready version
Hotfix | hotfix-YYYYMMDD-N | After hotfix merges to main | Emergency fix tracking
Evaluation pass | eval-pass-YYYYMMDD | When benchmark suite passes all thresholds | Evaluation baseline for regression detection


#### Tag Commands Reference
# Sprint tag — annotated (stores sprint summary)
git tag -a sprint-4-done -m 'Sprint 4: SQL 3-stage pipeline end-to-end tested. sql_success_rate=0.97'
git push origin sprint-4-done
# Semantic version release
git checkout main
git merge --no-ff develop -m 'chore(release): merge develop into main for v1.0.0'
git tag -a v1.0.0 -m 'Release v1.0.0 — 10-sprint ERP Agentic RAG system'
git push origin main --tags
# View all sprint progress at a glance
git tag -l 'sprint-*' | sort
# Diff between two sprints (what changed in sprint 5)
git diff sprint-4-done sprint-5-done --stat

### 3.5 — CHANGELOG.md Structure
The CHANGELOG.md file tracks progress at the sprint level. Each sprint gets one entry. It is committed at the end of every sprint before the sprint tag is created.
# CHANGELOG
## [Unreleased]
- Ongoing work not yet tagged
## [sprint-10-done] — 2026-06-14
### Added
- Security test suite: SQL injection, cross-tenant isolation
- Load test: Locust config for 50 concurrent users
- v1.0.0 release tag on main
### Changed
- README.md fully rewritten
- ARCHITECTURE.md final version
## [sprint-4-done] — 2026-05-10
### Added
- SQL 3-stage pipeline: ValidationReport model (domain/models/sql_pipeline.py)
- query_executor.py logs every ExecutionResult to MongoDB query_log collection
- SQL pipeline metrics: sql_stage1_latency, sql_stage2_errors, sql_stage3_rows
### Fixed
- Tenant filter bypass: executor now hard-raises on is_valid=False
### Tested
- sql_benchmark.py: 97% success rate on 20 test queries
- test_sql_e2e.py: full NL → ValidationReport → ExecutionResult → answer
## [sprint-1-done] — 2026-04-19
### Added
- observability/prometheus_metrics.py — all counters and histograms defined
- observability/structured_logger.py — JSON log format with trace_id
- GET /metrics endpoint added to admin.py
- Prometheus container added to docker-compose.yaml

### 3.6 — CI/CD Pipeline
Trigger | Jobs Run | On Failure | Deploys To
Push to any feature/sprint branch | lint (ruff) + type check (mypy) + unit tests | Block merge | Nothing
Push to develop | unit + integration + SQL benchmark + classifier benchmark | Slack alert + block deploy | Staging
Push to main | full suite + security tests + load test (subset) | Rollback | Production
New sprint-N-done tag | Run full eval suite, post results to PR/Slack | Alert only | Nothing
New vX.Y.Z tag | Build Docker image, push to registry, deploy | Rollback with git revert | Production


#### CI YAML Sketch
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
lint:
runs-on: ubuntu-latest
steps:
- run: ruff check src/
- run: mypy src/ --ignore-missing-imports
unit-tests:
steps:
- run: pytest src/tests/unit/ --cov=src --cov-fail-under=80
integration-tests:
if: github.ref == 'refs/heads/develop' || startsWith(github.ref, 'refs/heads/sprint-')
steps:
- run: docker-compose -f docker/docker-compose.yaml up -d
- run: pytest src/tests/integration/ -v
sql-benchmark:
if: github.ref == 'refs/heads/develop'
steps:
- run: python evaluation/benchmarks/sql_benchmark.py || exit 1
classifier-benchmark:
if: github.ref == 'refs/heads/develop'
steps:
- run: python evaluation/benchmarks/classifier_benchmark.py || exit 1
security-tests:
if: github.ref == 'refs/heads/main'
steps:
- run: pytest src/tests/security/ -v

### 3.7 — Weekly Git Ritual
This is the exact sequence of git commands performed each week. It is a ritual — not optional.
Day | Action | Command
Monday (sprint start) | Create sprint branch from develop | git checkout develop && git pull && git checkout -b sprint-N/theme
Monday (sprint start) | Optional: tag sprint start | git tag sprint-N-start && git push origin sprint-N-start
Mon–Fri (daily) | Create feature sub-branches per task | git checkout -b feature/task-name sprint-N/theme
Mon–Fri (daily) | Commit with conventional message | git commit -m 'feat(scope): description'
Mon–Fri (daily) | Push feature branch | git push origin feature/task-name
Mon–Fri (task done) | Merge feature into sprint branch | git checkout sprint-N/theme && git merge --no-ff feature/task-name
Mon–Fri (task done) | Delete merged feature branch | git branch -d feature/task-name && git push origin --delete feature/task-name
Friday (sprint end) | Final push of sprint branch | git push origin sprint-N/theme
Friday (sprint end) | Open PR: sprint-N → develop | GitHub UI — requires CI green + 1 approval
Friday (sprint end) | Update CHANGELOG.md on sprint branch | vim CHANGELOG.md && git commit -m 'docs(changelog): sprint N done'
Friday (sprint end) | Merge PR to develop | GitHub UI merge (no-ff)
Friday (sprint end) | Tag the sprint | git tag -a sprint-N-done -m 'Sprint N complete' && git push origin sprint-N-done
Friday (sprint end) | Delete sprint branch remotely | git push origin --delete sprint-N/theme


### 3.8 — Hotfix Protocol
Hotfixes bypass the sprint cycle. They branch from develop (not from a sprint branch), fix the issue with minimum code change, and merge to BOTH develop AND main. They are tagged immediately.

# Step 1: Branch from develop (not from sprint branch)
git checkout develop && git pull
git checkout -b hotfix/tenant-filter-bypass
# Step 2: Fix. Commit with 'security' or 'fix' type
git commit -m 'security(sql): enforce tenant_id check in executor Stage 3'
# Step 3: Merge to develop
git checkout develop && git merge --no-ff hotfix/tenant-filter-bypass
git push origin develop
# Step 4: Merge to main (if main is in production)
git checkout main && git merge --no-ff hotfix/tenant-filter-bypass
git tag -a hotfix-20260510-1 -m 'Hotfix: tenant filter bypass in SQL executor'
git push origin main --tags
# Step 5: Delete hotfix branch
git branch -d hotfix/tenant-filter-bypass
git push origin --delete hotfix/tenant-filter-bypass
# Step 6: Cherry-pick into current sprint branch if needed
git checkout sprint-5/middleware-hardening
git cherry-pick <hotfix-commit-hash>

## 4. Progress Tracking & Visibility

### 4.1 — Sprint Progress Checklist Template
This template is committed as SPRINT.md at the root of every sprint branch on Monday. It is updated daily and committed. The final version is committed before the sprint PR is opened on Friday.
# Sprint N — [Theme] — YYYY-MM-DD to YYYY-MM-DD
## Status: IN PROGRESS | DONE | BLOCKED
## Tasks
- [ ] Task 1: description (owner: @dev1, due: Wed)
- [ ] Task 2: description (owner: @dev1, due: Thu)
- [x] Task 3: description — DONE (merged: feature/task-3)
## Definition of Done
- [ ] All tasks merged to sprint branch
- [ ] CI green on sprint branch
- [ ] CHANGELOG.md updated
- [ ] sprint-N-done tag pushed
- [ ] PR opened and approved
## Blockers
- Waiting on ERP test DB access (unblocked by @erp-team on Tue)
## Notes
- Discovered: query_executor.py missing query_id generation — added to task list

### 4.2 — Git Log as Progress Report
At any point, the following commands give an instant progress report:
# See all completed sprint milestones
git tag -l 'sprint-*' --sort=version:refname
# See what was done in sprint 4
git log sprint-3-done..sprint-4-done --oneline
# See all files changed in sprint 4
git diff sprint-3-done sprint-4-done --stat
# See which features are in develop but not yet in main
git log main..develop --oneline
# See all sprint tags with their messages
git tag -l 'sprint-*' -n1
# Full diff of what changed this week (current sprint vs develop)
git diff develop HEAD --stat

### 4.3 — Semantic Versioning Rules
Version Bump | Rule | Trigger | Example
PATCH (0.0.X) | Bug fix, prompt tuning, test addition, doc update | Hotfix merged to main | v1.0.0 → v1.0.1
MINOR (0.X.0) | New feature, new agent, new middleware, new route | Sprint milestone merged to main | v1.0.0 → v1.1.0
MAJOR (X.0.0) | Breaking API change, new required JWT claim, DB schema migration | Architecture change | v1.0.0 → v2.0.0

After v1.0.0 (end of Sprint 10), every new feature sprint creates a MINOR bump. Every hotfix creates a PATCH bump. A MAJOR bump requires an explicit decision meeting — it signals a breaking change that consumers of the API must adapt to.


### 4.4 — .gitignore Critical Rules
ALWAYS ignore | NEVER ignore
.env, .env.test, .env.prod — real secrets | evaluation/benchmarks/data/*.json — test fixtures
mongodb_data/ — database files | CHANGELOG.md — progress record
__pycache__/, *.pyc | SPRINT.md — sprint status
logs/ — runtime logs | src/tests/fixtures/*.sql — seed scripts
*.wt, WiredTiger* — MongoDB internal | evaluation/benchmarks/data/ — benchmark cases
node_modules/ (if any) | ARCHITECTURE.md — architecture decisions


---
## GIT QUICK REFERENCE

### Branch names
- Sprint:   sprint-N/theme          (e.g. sprint-1/observability)
- Feature:  feature/short-desc      (e.g. feature/prometheus-metrics)
- Hotfix:   hotfix/short-desc
- Experiment: experiment/desc       (NEVER merges to develop)

### Commit types
feat | fix | test | refactor | docs | chore | perf | security

### Sprint close sequence
1. git merge --no-ff sprint-N/theme → develop
2. git tag -a sprint-N-done -m "Sprint N: [summary]"
3. git push origin develop sprint-N-done
4. git push origin --delete sprint-N/theme

### Release sequence (Sprint 10)
1. git merge --no-ff develop → main
2. git tag -a v1.0.0 -m "Release v1.0.0"
3. git push origin main --tags
---
