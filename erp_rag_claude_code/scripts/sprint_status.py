#!/usr/bin/env python3
"""
sprint_status.py — Track sprint progress for the ERP Agentic RAG project.

Usage:
    python3 scripts/sprint_status.py                    # show current status
    python3 scripts/sprint_status.py --mark-done 1      # close sprint 1
    python3 scripts/sprint_status.py --start 2          # start sprint 2
    python3 scripts/sprint_status.py --release v1.0.0   # mark release
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / ".sprint_state.json"

SPRINT_THEMES = {
    1:  "Observability Foundation",
    2:  "Evaluation Framework",
    3:  "DI Hardening + Auth",
    4:  "SQL Pipeline End-to-End",
    5:  "Middleware Stack Hardening",
    6:  "Worker Reliability",
    7:  "Hybrid Agent",
    8:  "Model Selection + Degraded Mode",
    9:  "Query Intelligence",
    10: "Hardening & v1.0.0 Release",
}

SPRINT_BRANCH = lambda n: f"sprint-{n}/{SPRINT_THEMES[n].lower().replace(' ', '-').replace('+', 'and').replace('/', '-').replace('&', 'and')[:30]}"

SPRINT_DOD = {
    1: [
        "GET /metrics returns valid Prometheus format",
        "Every middleware logs JSON with trace_id",
        "auth_failure_rate, rbac_violation_rate, pii_detection_rate all increment",
        "structured_logger replaces all raw prints",
        "Unit tests for observability >= 80% coverage",
    ],
    2: [
        "sql_benchmark.py runs 20 queries — reports pass/fail",
        "CI fails if sql_success_rate < 0.95 or hallucination_rate > 0.05",
        "hallucination_scorer.py returns grounding_score 0.0–1.0",
        "rag_benchmark.py runs 15 retrieval cases",
        "All benchmark scripts exit 0 on pass, 1 on fail",
    ],
    3: [
        "container.validate() raises on missing binding at startup",
        "Auth integration test: login → JWT → protected route → 200",
        "All 4 RBAC roles tested (ADMIN/MANAGER/ANALYST/VIEWER)",
        "All token failure cases return 401",
        "DI factory unit test with mocked dependencies",
    ],
    4: [
        "sql_benchmark.py passes >= 95% on ERP test database",
        "ValidationReport.has_tenant_filter=False blocks Stage 3",
        "All non-SELECT SQL blocked by validator",
        "Every ExecutionResult has query_id in MongoDB query_log",
        "SQL pipeline metrics visible in Prometheus",
    ],
    5: [
        "Rate limit: 60 req/min user, 200 req/min IP — verified",
        "ANALYST role cannot query finance_schema — 403 verified",
        "PII masking: email, phone, NID, taxId >= 98% recall",
        "Full middleware stack adds < 20ms overhead",
        "auth_failure_rate, rbac_violation_rate, pii_detection_rate in Prometheus",
    ],
    6: [
        "ingest_task retries 3× then writes to failed_tasks",
        "SOP/BPMN/tax_circular chunkers produce expected chunk counts",
        "embed_task is idempotent — no duplicate vectors",
        "GET /admin/jobs/{job_id} returns status",
        "Worker metrics in Prometheus",
    ],
    7: [
        "asyncio.gather fires SQL + RAG simultaneously",
        "Synthesis LLM merges both sources into one answer",
        "SQL failure falls back to RAG-only (not 500)",
        "20 hybrid test queries all return with both sources cited",
        "Hybrid path p95 < 8 seconds",
    ],
    8: [
        "model_selector falls back to vLLM when OpenAI returns 5xx",
        "All LLMs fail → HTTP 503 with degraded=true",
        "Circuit breaker opens after 5 failures for 60s",
        "llm_failure_rate metric increments on every failure",
        "Kaggle notebook startup documented",
    ],
    9: [
        "classifier_benchmark.py runs 50 labeled queries",
        "Overall classifier accuracy >= 92% — CI gate",
        "Arabic queries routed correctly",
        "10 harmful queries all return decision=blocked",
        "Query rewriter tested on 15 ambiguous queries",
    ],
    10: [
        "100 SQL injection attempts — zero bypass validation",
        "Cross-tenant isolation: tenant_A cannot see tenant_B data",
        "Load test: p95 < 3s, p99 < 8s at 50 concurrent users",
        "README.md fully updated",
        "v1.0.0 git tag on main with CHANGELOG",
    ],
}


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "current_sprint": None,
        "completed_sprints": [],
        "release": None,
        "started_at": None,
    }


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def git_current_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def git_tags() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "tag", "-l", "sprint-*"],
            capture_output=True, text=True, check=True
        )
        return [t for t in result.stdout.strip().split("\n") if t]
    except Exception:
        return []


def show_status(state: dict) -> None:
    current = state.get("current_sprint")
    completed = state.get("completed_sprints", [])
    release = state.get("release")
    branch = git_current_branch()
    tags = git_tags()

    print("=" * 60)
    print("  ERP Agentic RAG — Sprint Status")
    print("=" * 60)

    if release:
        print(f"\n🎉 RELEASED: {release}")

    print(f"\n📍 Git branch: {branch}")
    print(f"🏷  Sprint tags: {', '.join(tags) if tags else 'none yet'}")

    print(f"\n✅ Completed sprints: {completed if completed else 'none'}")

    if current:
        theme = SPRINT_THEMES.get(current, "Unknown")
        print(f"\n🔄 CURRENT SPRINT: {current} — {theme}")
        print(f"   Branch: sprint-{current}/{theme.lower()[:20]}...")
        print(f"\n   Definition of Done:")
        dod = SPRINT_DOD.get(current, [])
        for item in dod:
            tag = f"sprint-{current}-done"
            done = tag in tags
            icon = "✅" if done else "⬜"
            print(f"     {icon} {item}")
    else:
        if not completed:
            print("\n⚡ No sprint active. Start sprint 1:")
            print("   python3 scripts/sprint_status.py --start 1")
        else:
            next_sprint = max(completed) + 1 if completed else 1
            if next_sprint <= 10:
                print(f"\n⚡ Next sprint: {next_sprint} — {SPRINT_THEMES.get(next_sprint, '')}")
                print(f"   Start with: python3 scripts/sprint_status.py --start {next_sprint}")
            else:
                print("\n🎉 All 10 sprints complete! Ready for v1.0.0 release.")

    print("\n" + "=" * 60)
    print("Next steps:")
    if current:
        print(f"  1. @planner  — Plan sprint {current} tasks")
        print(f"  2. @executor — Implement task N")
        print(f"  3. @tester   — Test task N")
        print(f"  4. @committer— Commit task N")
        print(f"  5. Repeat until DoD complete")
        print(f"  6. python3 scripts/sprint_status.py --mark-done {current}")
    print()


def start_sprint(n: int, state: dict) -> None:
    if n not in SPRINT_THEMES:
        print(f"❌ Sprint {n} does not exist (valid: 1–10)")
        sys.exit(1)
    if n in state.get("completed_sprints", []):
        print(f"❌ Sprint {n} already completed")
        sys.exit(1)

    state["current_sprint"] = n
    state["started_at"] = str(date.today())
    save_state(state)

    theme = SPRINT_THEMES[n]
    branch = f"sprint-{n}/{theme.lower().replace(' ', '-').replace('+', 'and')[:30].rstrip('-')}"

    print(f"✅ Sprint {n} started: {theme}")
    print(f"\nGit commands to run:")
    print(f"  git checkout develop && git pull")
    print(f"  git checkout -b {branch}")
    print(f"  git tag sprint-{n}-start && git push origin sprint-{n}-start")
    print(f"\nThen run: python3 scripts/read_docs.py --sprint {n}")


def mark_done(n: int, state: dict) -> None:
    if state.get("current_sprint") != n:
        print(f"⚠️  Sprint {n} is not the current sprint ({state.get('current_sprint')})")

    completed = state.get("completed_sprints", [])
    if n not in completed:
        completed.append(n)
    state["completed_sprints"] = sorted(completed)
    state["current_sprint"] = None
    save_state(state)

    print(f"✅ Sprint {n} marked as done")
    print(f"   Tag: git tag -a sprint-{n}-done -m 'Sprint {n}: {SPRINT_THEMES[n]}'")
    print(f"   Next: python3 scripts/sprint_status.py --start {n+1}")


def mark_release(version: str, state: dict) -> None:
    state["release"] = version
    save_state(state)
    print(f"✅ Release {version} recorded")
    print(f"   Git: git tag -a {version} -m 'Release {version}' && git push origin main --tags")


def main():
    parser = argparse.ArgumentParser(description="Sprint status tracker")
    parser.add_argument("--start",      type=int, help="Start sprint N")
    parser.add_argument("--mark-done",  type=int, help="Mark sprint N as done", dest="mark_done")
    parser.add_argument("--release",    type=str, help="Mark a release version")
    args = parser.parse_args()

    state = load_state()

    if args.start:
        start_sprint(args.start, state)
    elif args.mark_done:
        mark_done(args.mark_done, state)
    elif args.release:
        mark_release(args.release, state)
    else:
        show_status(state)


if __name__ == "__main__":
    main()
