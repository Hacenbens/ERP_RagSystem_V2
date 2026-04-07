#!/usr/bin/env python3
"""
start_session.py — Run this FIRST at the start of every Claude Code session.

What it does:
1. Extracts and caches source-of-truth from DOCX files
2. Shows current sprint status
3. Prints the next recommended action
4. Validates git state

Usage:
    python3 scripts/start_session.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def run(cmd: str, capture: bool = True) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    return result.stdout.strip() if capture else ""


def check_git() -> None:
    print("\n📌 GIT STATE")
    print("-" * 40)

    branch = run("git branch --show-current")
    print(f"  Branch:  {branch}")

    status = run("git status --short")
    if status:
        print(f"  Uncommitted changes:")
        for line in status.split("\n")[:10]:
            print(f"    {line}")
    else:
        print(f"  Working tree: clean")

    last_commits = run("git log --oneline -5")
    print(f"  Last commits:")
    for line in last_commits.split("\n"):
        print(f"    {line}")

    tags = run("git tag -l 'sprint-*' --sort=version:refname")
    if tags:
        print(f"  Sprint tags: {tags.replace(chr(10), ', ')}")
    else:
        print(f"  Sprint tags: none yet")


def check_docs() -> None:
    print("\n📚 SOURCE OF TRUTH DOCS")
    print("-" * 40)

    docs_dir = ROOT / "docs"
    mapping = docs_dir / "ERP_RAG_Architecture_Mapping.docx"
    sprint  = docs_dir / "ERP_RAG_Sprint_Plan_GitStrategy.docx"
    cache   = docs_dir / "source_of_truth.md"

    for name, path in [("Architecture Mapping", mapping), ("Sprint Plan", sprint)]:
        if path.exists():
            size = path.stat().st_size // 1024
            print(f"  ✓ {name}: {path.name} ({size}KB)")
        else:
            print(f"  ✗ MISSING: {name} — place at {path}")

    if cache.exists():
        size = cache.stat().st_size // 1024
        print(f"  ✓ Cached source_of_truth.md ({size}KB)")
    else:
        print(f"  ⚡ Cache not built yet — will build now")


def build_cache() -> None:
    print("\n🔄 BUILDING SOURCE OF TRUTH CACHE")
    print("-" * 40)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "read_docs.py")],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("  ✓ Cache built successfully")
    else:
        print(f"  ⚠ Cache build had issues:")
        print(f"    {result.stderr[:200]}")


def show_sprint_status() -> None:
    print("\n📊 SPRINT STATUS")
    print("-" * 40)
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sprint_status.py")],
        capture_output=False
    )


def print_agent_guide() -> None:
    print("\n🤖 AGENT WORKFLOW GUIDE")
    print("-" * 40)
    print("""
  For a new task, follow this sequence:

  1. PLAN
     Tell Claude: "Act as @planner — plan the next task for sprint N"
     Claude reads agents/planner.md and docs/source_of_truth.md

  2. EXECUTE
     Tell Claude: "Act as @executor — implement: [task from plan]"
     Claude reads agents/executor.md and writes the code

  3. TEST
     Tell Claude: "Act as @tester — test: [task]"
     Claude reads agents/tester.md and writes + runs tests

  4. COMMIT
     Tell Claude: "Act as @committer — commit: [task]"
     Claude reads agents/committer.md and commits with proper convention

  For sprint close:
     Tell Claude: "Act as @committer — close sprint N"

  For quick source lookup:
     python3 scripts/read_docs.py --sprint 4
     python3 scripts/read_docs.py --section "SQL Pipeline"
     python3 scripts/read_docs.py --section "Middleware"
""")


def main() -> None:
    print("=" * 60)
    print("  ERP Agentic RAG — Session Start")
    print("=" * 60)

    check_docs()

    # Build cache if needed
    cache = ROOT / "docs" / "source_of_truth.md"
    if not cache.exists():
        build_cache()

    check_git()
    show_sprint_status()
    print_agent_guide()

    print("=" * 60)
    print("  Session ready. Start with @planner.")
    print("=" * 60)


if __name__ == "__main__":
    main()
