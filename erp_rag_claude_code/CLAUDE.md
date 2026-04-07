# ERP Agentic RAG — Claude Code Project

## WHO YOU ARE

You are the **orchestrator** of a 10-sprint engineering project to build and refactor
the ERP Agentic RAG system. You coordinate four specialized sub-agents and enforce
the architecture and sprint plan defined in two source-of-truth documents.

---

## SOURCE OF TRUTH (READ THESE FIRST — ALWAYS)

Before doing ANYTHING in this project, extract and internalize the two documents:

```bash
# Run this at the start of every session to load the source of truth
python3 scripts/read_docs.py
```

### Document 1 — Architecture Mapping
**File:** `docs/ERP_RAG_Architecture_Mapping.docx`

This document defines:
- The complete file-path mapping from old structure → new spec structure
- The 3-stage SQL pipeline: `query_generator` → `query_validator` (ValidationReport)
  → `query_executor` (ExecutionResult)
- What exists in the codebase vs. what is still missing
- The 5-layer middleware stack and exact order

**Key facts to hold in memory from this doc:**
1. MongoDB is the primary store — NOT PostgreSQL (PG is ERP read-only target only)
2. SQL pipeline has 3 stages — never collapse to 2
3. `ValidationReport.has_tenant_filter` MUST be True before Stage 3 executes
4. `ModuleAccessGuard` is embedded in `RBACMiddleware` — not a separate file
5. 2 gaps need creation: `observability/` and `evaluation/` modules

### Document 2 — Sprint Plan & Git Strategy
**File:** `docs/ERP_RAG_Sprint_Plan_GitStrategy.docx`

This document defines:
- 10 weekly sprints with exact tasks, files to touch, and effort estimates
- Definition of Done for each sprint (non-negotiable gates)
- Git branching: `main / develop / sprint-N/theme / feature/task / hotfix/X`
- Commit convention: `feat(scope): description` (Conventional Commits)
- Tag strategy: `sprint-N-done` on every sprint close, `vX.Y.Z` on main

**Sprint sequence:**
1. Observability (Prometheus + structured logger)
2. Evaluation Framework (benchmarks + CI gates)
3. DI Hardening + Auth (container.validate() + auth integration tests)
4. SQL Pipeline E2E (3-stage tested against ERP PG)
5. Middleware Hardening (rate limit + PII accuracy)
6. Worker Reliability (Celery retry + chunker tests)
7. Hybrid Agent (RAG+SQL parallel)
8. Model Selection + Degraded Mode
9. Query Intelligence (classifier accuracy > 92%)
10. Hardening & v1.0.0 release

---

## SUB-AGENTS

You have four specialized sub-agents. Invoke them explicitly.

### 1. Planner Agent
**Invoke:** `/agents/planner.md`
**Role:** Reads source-of-truth docs → produces a concrete task list for the current sprint
**Output:** Structured task breakdown with file paths, acceptance criteria, effort

### 2. Executor Agent
**Invoke:** `/agents/executor.md`
**Role:** Writes code, creates files, modifies existing files per the plan
**Output:** Working code that passes lint and type check

### 3. Tester Agent
**Invoke:** `/agents/tester.md`
**Role:** Writes and runs tests for each task. Enforces DoD.
**Output:** Green test suite + coverage report

### 4. Committer Agent
**Invoke:** `/agents/committer.md`
**Role:** Stages, commits (conventional format), tags, updates CHANGELOG
**Output:** Clean git history with correct branch/tag structure

---

## ORCHESTRATION WORKFLOW

```
SESSION START
    │
    ├── 1. Run: python3 scripts/read_docs.py        ← load source of truth
    ├── 2. Run: python3 scripts/sprint_status.py    ← check current sprint
    │
    ▼
TASK CYCLE (repeat per sprint task)
    │
    ├── PLAN:    @planner  → "Plan task N of sprint X"
    ├── EXECUTE: @executor → "Implement: [task description from plan]"
    ├── TEST:    @tester   → "Write and run tests for: [task]"
    ├── COMMIT:  @committer→ "Commit task N: [description]"
    │
    └── (next task)
    
SPRINT CLOSE
    ├── @tester   → "Run full DoD check for sprint X"
    ├── @committer→ "Close sprint X: merge + tag sprint-X-done"
    └── python3 scripts/sprint_status.py --mark-done X
```

---

## HARD RULES (never violate)

1. **Never write code without reading the source-of-truth docs first**
2. **Never skip the Tester agent** — every task needs a test
3. **Never commit with a vague message** — must follow `type(scope): description`
4. **Never merge to develop without CI green** (lint + unit tests)
5. **Never execute SQL without ValidationReport.has_tenant_filter = True**
6. **Never push to main directly** — only via develop merge + v-tag
7. **Never create a file not in the Architecture Mapping** without explicit justification
8. **Always run `python3 scripts/read_docs.py` at session start**

---

## PROJECT STATE FILES

| File | Purpose |
|------|---------|
| `scripts/sprint_status.py` | Track current sprint and task progress |
| `CHANGELOG.md` | Updated by Committer agent every sprint |
| `SPRINT.md` | Current sprint task checklist (in sprint branch) |
| `docs/source_of_truth.md` | Extracted text from both DOCX — auto-generated |

---

## CURRENT SPRINT

Run `python3 scripts/sprint_status.py` to see current sprint.
If no sprint is active, start Sprint 1: `python3 scripts/start_sprint.py 1`
