
# Sprint 8 — Model Selection + Degraded Mode — Task Plan
**Branch:** `sprint-8/model-selection`
**Date planned:** 2026-04-26
**Source of truth:** `docs/source_of_truth.md` §SPRINT 8 + §9.6 + §9.7 + §9.8 + §10

---

## Codebase Audit Summary

| Status | Item |
|--------|------|
| ✓ EXISTS | `src/domain/ports/llm_port.py` — `LLMPort` ABC (Sprint 7) |
| ✓ EXISTS | `src/observability/prometheus_metrics.py` — `LLM_FAILURE_RATE`, `CIRCUIT_BREAKER_STATE`, `DEGRADED_MODE_ACTIVATIONS` declared (no code calls them yet) |
| ✓ EXISTS | `src/prompts/registry.py` — `PromptRegistry` YAML loader |
| ✓ EXISTS | `src/prompts/versions/rag_answer_v1.yaml` + `hybrid_orchestrator_v1.yaml` |
| ✓ EXISTS | `src/prompts/schemas/rag_output.schema.json` + `hybrid_output.schema.json` |
| ✓ EXISTS | `src/agents/base_agent.py` — `BaseAgent` pattern |
| ✓ EXISTS | `src/infrastructure/nlp/stub_classifier.py` — `StubClassifier` (test-only) |
| ✗ MISSING | `src/domain/ports/model_selector_port.py` |
| ✗ MISSING | `src/domain/ports/degraded_mode_port.py` |
| ✗ MISSING | `src/infrastructure/generation/` — entire directory |
| ✗ MISSING | `src/infrastructure/generation/openai_llm_client.py` |
| ✗ MISSING | `src/infrastructure/generation/vllm_llm_client.py` |
| ✗ MISSING | `src/infrastructure/generation/model_selector.py` |
| ✗ MISSING | `src/infrastructure/generation/degraded_mode_service.py` |
| ✗ MISSING | `src/agents/query_classifier_agent.py` |
| ✗ MISSING | `src/prompts/versions/classifier_v1.yaml` |
| ✗ MISSING | `src/prompts/versions/sql_generator_v1.yaml` |
| ✗ MISSING | `src/prompts/versions/evaluator_v1.yaml` |
| ✗ MISSING | `src/prompts/schemas/classifier_output.schema.json` |
| ✗ MISSING | `src/prompts/schemas/sql_generator_output.schema.json` |
| ✗ MISSING | `src/prompts/schemas/evaluator_output.schema.json` |
| ✗ MISSING | `src/observability/metrics_collector.py` |
| ✗ MISSING | `src/tests/unit/test_model_selector.py` |
| ✗ MISSING | `src/tests/integration/test_degraded_mode.py` |
| ✗ MISSING | `notebooks/kaggle_llm_server.ipynb` |

### Flags for Executor
- `LLM_FAILURE_RATE`, `CIRCUIT_BREAKER_STATE`, `DEGRADED_MODE_ACTIVATIONS` are already
  **declared** in prometheus_metrics.py — do **not** re-declare; import and call them.
- All tests must use mocked httpx / openai stubs — no real API keys required.
- `vllm_llm_client.py` must use `httpx` (already a project dependency); no `vllm` package needed.
- `notebooks/` directory does not exist — create it.

---

## Task Sequence (dependency order)

```
TASK 1 (ports ABCs)
  └── TASK 2 (LLM clients)
        └── TASK 3 (ModelSelector + circuit breaker)
              ├── TASK 4 (DegradedModeService + cache)
              │     └── TASK 6 (integration test: degraded mode)
              └── TASK 5 (unit tests: ModelSelector)
TASK 7 (QueryClassifierAgent + classifier_v1.yaml)  ← parallel with TASK 3+
TASK 8 (sql_generator + evaluator YAMLs)            ← parallel, no deps
TASK 9 (MetricsCollector)                           ← parallel, no deps
TASK 10 (Kaggle notebook)                           ← parallel, no deps
```

---

## Tasks

### TASK 1 — ModelSelectorPort + DegradedModePort ABCs
```
Status:      ✅ DONE
Files:       src/domain/ports/model_selector_port.py
             src/domain/ports/degraded_mode_port.py
Action:      CREATE
Effort:      0.5d
Depends on:  NONE
Acceptance:
  - ModelSelectorPort(ABC).complete(prompt, temperature, max_tokens) → str
      (acts as LLMPort but delegates to the currently selected provider)
  - DegradedModePort(ABC).get_cached(query_hash: str) → str | None
  - DegradedModePort(ABC).set_cached(query_hash: str, answer: str) → None
  - Both are pure ABCs — no infrastructure imports
Test file:   (ABCs — import smoke test only; covered by TASK 5 + 6)
```

### TASK 2 — GeminiLLMClient + vLLMLLMClient
```
Status:      ✅ DONE
Files:       src/infrastructure/generation/__init__.py
             src/infrastructure/generation/gemini_llm_client.py
             src/infrastructure/generation/vllm_llm_client.py
Action:      CREATE
Effort:      0.5d
Depends on:  TASK 1
Acceptance:
  - OpenAILLMClient(LLMPort): calls openai.chat.completions.create (sync wrapper)
      Constructor: api_key, model (default "gpt-4o"), base_url (optional)
      Raises ConnectionError on httpx.ConnectError / openai.APIConnectionError / 5xx
  - vLLMLLMClient(LLMPort): calls self-hosted endpoint via httpx POST
      Constructor: base_url (e.g. "http://localhost:8000"), model
      Raises ConnectionError on network error / non-2xx response
  - Both use structured_logger at entry and exit
  - No hardcoded keys — all config via constructor args (injected from env via DI)
Test file:   src/tests/unit/test_model_selector.py (mocked at httpx / openai level)
```

### TASK 3 — ModelSelector with circuit breaker + Gemini → vLLM fallback
```
Status:      ✅ DONE
File:        src/infrastructure/generation/model_selector.py
Action:      CREATE
Effort:      0.5d
Depends on:  TASK 2
Acceptance:
  - ModelSelector(LLMPort): wraps ordered list [primary: LLMPort, fallback: LLMPort]
  - .complete(prompt, temperature, max_tokens):
      1. If primary circuit is open → skip primary, try fallback
      2. Try primary; on ConnectionError:
           - increment LLM_FAILURE_RATE.labels(provider="openai")
           - record failure; if failures >= 5 → open circuit, set CIRCUIT_BREAKER_STATE=1
           - try fallback; on fallback failure → increment LLM_FAILURE_RATE.labels(provider="vllm")
           - raise LLMUnavailableError
      3. On primary success → reset failure count, CIRCUIT_BREAKER_STATE=0 → return answer
  - Circuit breaker: time.monotonic()-based; auto-resets after 60 s
  - LLMUnavailableError defined in src/domain/exceptions.py (or inline if not present)
  - Structured log at every provider attempt and outcome
Test file:   src/tests/unit/test_model_selector.py
```

### TASK 4 — DegradedModeService with per-query-hash answer cache
```
Status:      ✅ DONE
File:        src/infrastructure/generation/degraded_mode_service.py
Action:      CREATE
Effort:      0.5d
Depends on:  TASK 3
Acceptance:
  - DegradedModeService(DegradedModePort):
      Constructor: selector: ModelSelector, cache: dict[str, str] (default empty)
  - .complete(prompt: str, query_hash: str) → str:
      1. Try selector.complete(prompt)
      2. On success: set_cached(query_hash, answer); return answer
      3. On LLMUnavailableError:
           - get cached = get_cached(query_hash)
           - increment DEGRADED_MODE_ACTIVATIONS
           - if cached → return cached
           - return JSON string: {"degraded": true, "cached_answer": null,
                                  "answer": "Service temporarily unavailable."}
  - get_cached / set_cached backed by in-memory dict (injectable for tests)
  - Structured log: "degraded_mode.activated" with query_hash and cache_hit bool
Test file:   src/tests/integration/test_degraded_mode.py
```

### TASK 5 — Unit tests — ModelSelector (fallback + circuit breaker)
```
Status:      ✅ DONE
File:        src/tests/unit/test_model_selector.py
Action:      CREATE
Effort:      1d
Depends on:  TASK 3
Acceptance:  ≥ 15 tests:
  TestModelSelectorFallback
    - test_primary_success_returns_answer_without_calling_fallback
    - test_primary_connection_error_triggers_fallback
    - test_both_providers_fail_raises_llm_unavailable_error
    - test_primary_failure_increments_llm_failure_rate_counter
    - test_fallback_failure_increments_llm_failure_rate_counter_for_vllm
    - test_successful_call_does_not_increment_failure_counter
  TestCircuitBreaker
    - test_circuit_opens_after_five_consecutive_primary_failures
    - test_circuit_open_skips_primary_directly_to_fallback
    - test_circuit_state_gauge_is_1_when_open
    - test_circuit_state_gauge_is_0_when_closed
    - test_circuit_resets_after_60_seconds (mock time.monotonic)
    - test_circuit_still_open_before_60_seconds_elapsed
    - test_successful_call_resets_failure_count
    - test_circuit_opens_only_after_exactly_5_failures_not_4
    - test_multiple_selectors_have_independent_circuits
Test file:   src/tests/unit/test_model_selector.py
```

### TASK 6 — Integration test — degraded mode (both LLMs return 503)
```
Status:      ✅ DONE (delivered with Task 4 — 27 tests in test_degraded_mode.py)
File:        src/tests/integration/test_degraded_mode.py
Action:      CREATE
Effort:      0.5d
Depends on:  TASK 4, TASK 5
Acceptance:  ≥ 8 tests:
  TestDegradedModeServiceBothFail
    - test_both_providers_fail_returns_degraded_json_not_exception
    - test_degraded_response_body_has_degraded_true_field
    - test_degraded_response_cached_answer_is_null_on_first_failure
    - test_degraded_mode_activations_counter_increments_per_degraded_response
  TestDegradedModeCacheFallback
    - test_prior_successful_answer_returned_as_cached_answer_on_degraded
    - test_different_query_hash_does_not_return_wrong_cached_answer
    - test_successful_request_does_not_increment_degraded_mode_activations
    - test_cache_hit_logs_cache_hit_true
Test file:   src/tests/integration/test_degraded_mode.py
```

### TASK 7 — QueryClassifierAgent + classifier_v1.yaml + schema
```
Status:      ✅ DONE (10/10 live accuracy on Gemini 2.5 Flash-Lite)
Files:       src/agents/query_classifier_agent.py
             src/prompts/versions/classifier_v1.yaml
             src/prompts/schemas/classifier_output.schema.json
Action:      CREATE
Effort:      1d
Depends on:  TASK 3 (LLMPort injection)
Acceptance:
  - QueryClassifierAgent(BaseAgent):
      Constructor: llm: LLMPort, registry: PromptRegistry
      .classify(query: str, erp_module: str | None) → RoutingDecision
        Loads "classifier_v1" from registry, builds prompt, calls llm.complete()
        Parses JSON → {"intent": "RAG|SQL|HYBRID|BLOCKED", "confidence": float, "reason": str}
        Returns RoutingDecision(intent=..., confidence=..., reason=...)
  - classifier_v1.yaml: system prompt instructing model to classify ERP queries
      Includes few-shot examples for each intent class
      schema_path: schemas/classifier_output.schema.json
  - StubClassifier kept as-is for tests — QueryClassifierAgent is the production path
  - ≥ 5 tests in src/tests/unit/test_agents.py (extend existing file):
      test_classifier_agent_returns_rag_intent_for_policy_query
      test_classifier_agent_returns_sql_intent_for_data_query
      test_classifier_agent_returns_hybrid_intent_for_combined_query
      test_classifier_agent_returns_blocked_for_harmful_query
      test_classifier_agent_parses_confidence_field
Test file:   src/tests/unit/test_agents.py (extend)
```

### TASK 8 — sql_generator_v1.yaml + evaluator_v1.yaml prompts
```
Status:      ☐ TODO
Files:       src/prompts/versions/sql_generator_v1.yaml
             src/prompts/versions/evaluator_v1.yaml
             src/prompts/schemas/sql_generator_output.schema.json
             src/prompts/schemas/evaluator_output.schema.json
Action:      CREATE
Effort:      0.5d
Depends on:  NONE
Acceptance:
  - sql_generator_v1.yaml: prompt for Stage 1 SQL generation
      Instructs model to produce {"sql": "...", "tables_used": [...], "confidence": float}
      Includes tenant_id injection instruction: always add WHERE tenant_id = '{tenant_id}'
  - evaluator_v1.yaml: LLM-as-judge prompt
      Instructs model to score answer grounding:
      {"grounding_score": float, "hallucination_rate": float, "faithfulness": float,
       "completeness": float, "relevance": float, "reasoning": str}
  - Both loadable via PromptRegistry without error
  - ≥ 3 tests added to src/tests/unit/test_prompt_registry.py
Test file:   src/tests/unit/test_prompt_registry.py (extend)
```

### TASK 9 — MetricsCollector (per-request accumulator + Prometheus flush)
```
Status:      ☐ TODO
File:        src/observability/metrics_collector.py
Action:      CREATE
Effort:      0.5d
Depends on:  NONE
Acceptance:
  - MetricsCollector dataclass — fields (all Optional[float] unless noted):
      classifier_latency_ms, rag_latency_ms, sql_latency_ms, hybrid_latency_ms
      tokens_prompt: int | None, tokens_completion: int | None
      llm_provider: str | None   ("openai" | "vllm")
      degraded: bool = False
  - .flush() → None:
      Observes non-None latency fields into erp_rag_query_latency_ms{stage}
      Observes token counts into erp_rag_tokens_used_total{type}
      If degraded=True → DEGRADED_MODE_ACTIVATIONS.inc() (only if not already counted)
      Idempotent: calling flush() twice must not double-count
  - .record_stage(stage: str, latency_ms: float) → None: convenience setter
  - ≥ 8 unit tests in src/tests/unit/test_metrics_collector.py
Test file:   src/tests/unit/test_metrics_collector.py
```

### TASK 10 — Kaggle notebook — external LLM/embedding server documentation
```
Status:      ☐ TODO
File:        notebooks/kaggle_llm_server.ipynb
Action:      CREATE
Effort:      0.5d
Depends on:  NONE
Acceptance:
  - Notebook cells cover:
      1. Install vllm (pip cell, marked as optional/GPU-only)
      2. Start vLLM OpenAI-compatible server: vllm serve <model> --port 8000
      3. Start embedding server: uvicorn embedding_server:app --port 8001
      4. Inject env vars: EMBEDDING_SERVER_URL, LLM_SERVER_URL, OPENAI_API_KEY
      5. Health check cell: GET /health on both servers
  - All markdown cells explain the purpose in plain English
  - Code cells are syntactically valid Python
  - ARCHITECTURE.md gets a one-line pointer to notebooks/kaggle_llm_server.ipynb
Test:        nbconvert --execute (markdown + code cells only, skip GPU cells)
```

---

## Definition of Done (Sprint 8)

```
[ ] ModelSelector falls back to vLLM when OpenAI returns 5xx — test_model_selector.py
[ ] All LLMs fail → HTTP 503 body {degraded: true, cached_answer: ...} (not 500) — test_degraded_mode.py
[ ] Circuit breaker opens after 5 consecutive failures, stays open 60 s — unit test with mocked time
[ ] LLM_FAILURE_RATE counter increments on every provider failure — verified via REGISTRY
[ ] CIRCUIT_BREAKER_STATE gauge = 1 when open, 0 when closed — verified via REGISTRY
[ ] DEGRADED_MODE_ACTIVATIONS counter increments on every degraded response — verified via REGISTRY
[ ] QueryClassifierAgent loads classifier_v1.yaml and returns valid RoutingDecision
[ ] MetricsCollector.flush() writes to Prometheus without double-counting
[ ] Kaggle notebook syntactically valid — cells pass nbconvert check
[ ] Full suite ≥ 1192 passing, 0 failures
[ ] ruff check src/ — zero new violations from Sprint 8 files
[ ] mypy — zero new errors in Sprint 8 files
[ ] Sprint tag sprint-8-done pushed, CHANGELOG updated
```

---

## Git Work

```bash
git checkout -b sprint-8/model-selection develop
# ... task commits ...
# PR → develop
# tag: sprint-8-done
```

### Commit plan (one commit per task)
```
feat(generation): add ModelSelectorPort and DegradedModePort ABCs (Task 1)
feat(generation): add OpenAILLMClient and vLLMLLMClient (Task 2)
feat(generation): add ModelSelector with circuit breaker and fallback (Task 3)
feat(generation): add DegradedModeService with query-hash answer cache (Task 4)
test(generation): add ≥15 unit tests for ModelSelector and circuit breaker (Task 5)
test(generation): add integration tests for degraded mode (Task 6)
feat(agents): add QueryClassifierAgent with classifier_v1 prompt (Task 7)
feat(prompts): add sql_generator_v1 and evaluator_v1 YAML prompts (Task 8)
feat(observability): add MetricsCollector per-request accumulator (Task 9)
docs(notebooks): add kaggle_llm_server.ipynb startup guide (Task 10)
docs(changelog): sprint 8 complete — model selection + degraded mode
```

---

## Blockers

- None — all port ABCs from Sprint 7 are on `develop`
- No real API keys needed — all Sprint 8 tests use stubs/monkeypatching
