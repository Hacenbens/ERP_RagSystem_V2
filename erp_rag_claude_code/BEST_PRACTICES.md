# Claude Code Best Practices — ERP Agentic RAG

This file contains hard-won best practices for getting high-quality,
consistent results from Claude Code on this project.

---

## 1. ALWAYS START WITH THE SESSION SCRIPT

```bash
python3 scripts/start_session.py
```

This loads the source-of-truth cache, shows sprint status, and prints
the agent workflow. **Without this, Claude has no memory of previous sessions.**

If the DOCX files have changed since last session, force a refresh:
```bash
python3 scripts/read_docs.py --no-cache
```

---

## 2. INVOKE AGENTS EXPLICITLY

Claude Code does not automatically know which agent to be.
You must tell it explicitly:

**Do this:**
```
Act as @planner — plan the next task for sprint 1
Act as @executor — implement task 2: create prometheus_metrics.py
Act as @tester — write and run tests for prometheus_metrics.py
Act as @committer — commit: feat(observability): add prometheus_metrics.py
```

**Don't do this:**
```
Add observability support  ← too vague, Claude will invent its own plan
```

---

## 3. ONE TASK PER EXCHANGE

Keep each agent invocation to a single task.
Multi-task prompts produce lower quality:

**Good:**
```
Act as @executor — implement TASK 1: create observability/prometheus_metrics.py
with these counters: REQUEST_TOTAL, AUTH_FAILURES, SQL_STAGE2_ERRORS
```

**Bad:**
```
Act as @executor — implement all of sprint 1
```

---

## 4. ALWAYS CONFIRM FILES BEFORE MODIFYING

Before any executor invocation, ask Claude to read the existing file:
```
Before implementing, show me the current content of:
src/infrastructure/erp/query_validator.py
```

This prevents Claude from overwriting important existing logic.

---

## 5. ALWAYS VALIDATE AGAINST SOURCE OF TRUTH

Before any implementation, ask the planner to confirm the file path:
```
Act as @planner — confirm: is src/observability/prometheus_metrics.py
the correct path per the Architecture Mapping document?
```

If Claude invents a path not in the Architecture Mapping, reject it:
```
That path is not in the Architecture Mapping. Check docs/source_of_truth.md
section "2. Complete File Path Mapping" and use the correct path.
```

---

## 6. CRITICAL SECURITY PROMPTS

For SQL pipeline tasks, always add this to the executor prompt:
```
SECURITY REQUIREMENT: The executor (Stage 3) must check:
1. report.is_valid == True
2. report.has_tenant_filter == True
3. report.is_select_only == True
before calling asyncpg. Never skip these checks.
```

For middleware tasks:
```
SECURITY REQUIREMENT: Middleware must execute in order:
Logging → Auth → RateLimit → RBAC → PIIMasking
A rejected request must NOT reach the next middleware layer.
```

---

## 7. TESTER QUALITY GATES

Tell the tester explicitly what to test:
```
Act as @tester — write tests for query_validator.py
Include:
1. Happy path: valid SELECT with tenant_id → ValidationReport(is_valid=True)
2. Security: INSERT statement → ValidationReport(is_valid=False, is_select_only=False)
3. Security: missing tenant_id → ValidationReport(has_tenant_filter=False)
4. Edge case: empty SQL string → ValidationReport(is_valid=False)
Then run: pytest src/tests/unit/test_query_validator.py -v
```

---

## 8. COMMITTER CONVENTIONS

Always tell the committer which type to use:
```
Act as @committer — commit with:
type: security
scope: sql-pipeline
subject: reject ValidationReport with missing tenant_id in executor
file: src/infrastructure/erp/query_executor.py
```

---

## 9. CONTEXT WINDOW MANAGEMENT

Claude Code has a context window. Long sessions accumulate context.
If Claude starts hallucinating file paths or forgetting constraints:

```bash
# Reload source of truth as a reminder
python3 scripts/read_docs.py --sprint 4
```

Then paste the output into the conversation:
```
Reminder — Sprint 4 definition from source of truth:
[paste output of read_docs.py --sprint 4]
```

---

## 10. NEVER TRUST CLAUDE'S MEMORY OF PREVIOUS SESSIONS

Claude Code does NOT remember previous sessions.
Every session starts fresh. The source-of-truth scripts exist specifically
to compensate for this. Always run `start_session.py` first.

---

## 11. HANDLING AMBIGUITY

When Claude gives you options or asks "should I do X or Y?",
resolve it by referencing the source-of-truth:

```
Check docs/source_of_truth.md — specifically section "2.5 Infrastructure: ERP SQL Pipeline"
The answer is defined there. Do not invent a solution.
```

---

## 12. SPRINT BRANCH HYGIENE

Before starting any executor work, verify the branch:
```
What is the current git branch?
Run: git branch --show-current
```

If not on the sprint branch, create it before proceeding.
Never let Claude commit to `develop` directly.

---

## 13. USEFUL QUICK COMMANDS

```bash
# What sprint are we on?
python3 scripts/sprint_status.py

# What does sprint 4 require?
python3 scripts/read_docs.py --sprint 4

# What does the architecture say about the SQL pipeline?
python3 scripts/read_docs.py --section "SQL Pipeline"

# What does the architecture say about middleware?
python3 scripts/read_docs.py --section "Middleware"

# What files exist in the project?
find src/ -name "*.py" | sort | grep -v __pycache__

# Run all tests
pytest src/tests/ -v --tb=short

# Check lint
ruff check src/

# Check types
mypy src/ --ignore-missing-imports
```

---

## 14. WHEN CLAUDE GETS STUCK

If Claude produces code that doesn't match the architecture:

1. Stop. Do not iterate on wrong code.
2. Run: `python3 scripts/read_docs.py --section "[relevant section]"`
3. Paste the relevant section into the conversation
4. Ask again with the context anchored:

```
The Architecture Mapping says:
[paste relevant section]

Given this constraint, implement [task] following the exact file path and pattern shown.
```

---

## 15. END OF SPRINT CHECKLIST

Run this exact sequence at sprint end:
```bash
# 1. Verify all DoD items
python3 scripts/sprint_status.py

# 2. Run full test suite
pytest src/tests/ -v

# 3. Lint + types
ruff check src/ && mypy src/ --ignore-missing-imports

# 4. Benchmark (if applicable)
python evaluation/benchmarks/sql_benchmark.py

# 5. Tell committer to close sprint
# Act as @committer — close sprint N: merge + tag
```
