"""
Executable form of ADR-001: nothing ships that nothing reaches.

The audit that opened Sprint 12 kept finding the same defect wearing different
clothes — a class, a port, a metric, built and tested and never called. Reviews
did not catch any of it, because "is anything actually reaching this?" is a
question about the whole repository and a diff only shows you one corner.

So it is a test. These fail on the change that introduces the dead code, not
during an audit six sprints later.

Each guard has an allowlist rather than a clever heuristic. An allowlist entry
is a claim a person made and can be argued with; a heuristic that silently
excuses things is how the original problem survived an import sweep.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).parents[3]

# Entry points: run by CI, a scheduler, or a person — never imported.
_ENTRY_POINTS = {
    "src/main.py",
    "evaluation/benchmarks/rag_benchmark.py",
    "evaluation/benchmarks/sql_benchmark.py",
    "evaluation/metrics/hallucination_scorer.py",
    "erp_rag_claude_code/scripts/read_docs.py",
    "erp_rag_claude_code/scripts/sprint_status.py",
    "erp_rag_claude_code/scripts/start_session.py",
    # Operator command, run by hand or from a deploy gate:
    #   python -m src.infrastructure.cli.reembed --dry-run
    "src/infrastructure/cli/reembed.py",
}


def _production_files() -> list[pathlib.Path]:
    out = []
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(("erp-rag-env-v2/", "src/tests/", ".")):
            continue
        if not rel.startswith(("src/", "helpers/", "evaluation/", "erp_rag_claude_code/")):
            continue
        out.append(path)
    return out


def _all_files() -> list[pathlib.Path]:
    return [
        p for p in REPO.rglob("*.py")
        if not p.relative_to(REPO).as_posix().startswith(("erp-rag-env-v2/", "."))
    ]


def _module_name(path: pathlib.Path) -> str:
    parts = list(path.relative_to(REPO).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: pathlib.Path) -> set[str]:
    """Modules this file imports, by dotted name."""
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


# ---------------------------------------------------------------------------
# No module lives only in its own tests
# ---------------------------------------------------------------------------

class TestEveryModuleIsReached:
    """A module imported only by its tests is dead, however well tested.

    ``__init__.py`` re-exports do not count as reaching a module. Both stores
    deleted in Sprint 12 were re-exported by their package, which is exactly
    why an import sweep reported them as live while nothing constructed either.
    """

    def test_no_production_module_is_reachable_only_from_tests(self):
        importers: dict[str, set[str]] = {}
        for path in _all_files():
            rel = path.relative_to(REPO).as_posix()
            for module in _imports(path):
                importers.setdefault(module, set()).add(rel)

        orphans = []
        for path in _production_files():
            rel = path.relative_to(REPO).as_posix()
            if path.name == "__init__.py" or rel in _ENTRY_POINTS:
                continue
            reached_by = {
                who for who in importers.get(_module_name(path), set())
                if not who.startswith("src/tests/") and not who.endswith("__init__.py")
            }
            if not reached_by:
                orphans.append(rel)

        assert not orphans, (
            "These modules are imported only by their own tests or by an "
            "__init__ re-export, so nothing at runtime reaches them:\n  "
            + "\n  ".join(sorted(orphans))
            + "\n\nEither wire it into the system, delete it, or add it to "
              "_ENTRY_POINTS with a reason."
        )


# ---------------------------------------------------------------------------
# No metric is exported without an emitter
# ---------------------------------------------------------------------------

class TestEveryMetricIsEmitted:
    """A metric nothing writes to reports a permanent zero.

    On a dashboard that is worse than a missing panel: a flat line reads as
    "measured, and healthy". Five metrics were in this state before Sprint 12,
    two of them for four sprints.
    """

    @staticmethod
    def _exported_metrics() -> list[str]:
        source = (REPO / "src/observability/prometheus_metrics.py").read_text()
        tree = ast.parse(source)
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "__all__"
            ):
                return [
                    el.value
                    for el in node.value.elts  # type: ignore[attr-defined]
                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                ]
        raise AssertionError("prometheus_metrics.py has no __all__")

    def test_every_exported_metric_has_a_production_importer(self):
        metrics = self._exported_metrics()
        assert metrics, "no metrics found to check"

        users: dict[str, set[str]] = {name: set() for name in metrics}
        for path in _production_files():
            if path.name == "prometheus_metrics.py":
                continue
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = path.relative_to(REPO).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and (
                    node.module.endswith("prometheus_metrics")
                ):
                    for alias in node.names:
                        if alias.name in users:
                            users[alias.name].add(rel)

        dead = sorted(name for name, who in users.items() if not who)
        assert not dead, (
            "These metrics are exported but no production module imports them, "
            "so they will report zero forever:\n  "
            + "\n  ".join(dead)
            + "\n\nEmit it from the code it measures, or delete it."
        )


# ---------------------------------------------------------------------------
# No pipeline stage is declared without being timed
# ---------------------------------------------------------------------------

class TestEveryStageIsTimed:
    def test_every_stage_member_is_used_by_a_stage_timer_call(self):
        """A Stage nobody times is a label that never appears in a query."""
        from src.observability.stage_timer import Stage

        source = "\n".join(
            p.read_text() for p in _production_files()
            if p.name != "stage_timer.py"
        )

        unused = [s.name for s in Stage if f"Stage.{s.name}" not in source]
        assert not unused, (
            "These Stage members are declared but never passed to stage_timer():\n  "
            + "\n  ".join(unused)
            + "\n\nTime the stage, or remove the member."
        )

    def test_stage_values_are_unique(self):
        """Two members sharing a value would silently merge two histograms."""
        from src.observability.stage_timer import Stage

        values = [s.value for s in Stage]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# One way to measure a stage
# ---------------------------------------------------------------------------

class TestNoSecondWayToTimeAStage:
    """Hand-rolled stage timing is what stage_timer replaced.

    Timing elsewhere is fine — request latency, Celery task duration, the
    circuit breaker's clock. What must not come back is a *pipeline stage*
    measuring itself with its own metric and its own unit, which is how
    SQL Stage 1 ended up reporting seconds while everything else reported
    nothing.
    """

    _MAY_TIME_THEMSELVES = {
        "src/middleware/LoggingMiddleware.py",      # whole-request latency
        "src/middleware/RateLimitMiddleware.py",    # sliding window
        "src/infrastructure/generation/circuit_breaker.py",  # open-state clock
        "src/infrastructure/auth/jwt_handler.py",   # token exp / iat
        "src/infrastructure/workers/tasks/ingest_task.py",   # celery task duration
        "src/infrastructure/workers/tasks/embed_task.py",    # celery task duration
        "src/use_cases/tasks/ingest_asset_use_case.py",      # reported in EmbedResult
        "src/use_cases/tasks/embed_asset_use_case.py",       # reported in EmbedResult
        "src/agents/hybrid_agent.py",               # end-to-end, not a stage
        "src/observability/stage_timer.py",         # the one implementation
        # Benchmarks time their own harness runs to report a score. They are
        # not part of the request path and emit no Prometheus series.
        "evaluation/benchmarks/rag_benchmark.py",
        "evaluation/benchmarks/sql_benchmark.py",
    }

    def test_pipeline_modules_do_not_roll_their_own_clock(self):
        offenders = []
        for path in _production_files():
            rel = path.relative_to(REPO).as_posix()
            if rel in self._MAY_TIME_THEMSELVES:
                continue
            text = path.read_text()
            if "time.perf_counter()" in text or "time.monotonic()" in text:
                offenders.append(rel)

        assert not offenders, (
            "These modules time themselves instead of using stage_timer():\n  "
            + "\n  ".join(sorted(offenders))
            + "\n\nUse stage_timer(Stage.X), or add the file to "
              "_MAY_TIME_THEMSELVES with the reason it is not a pipeline stage."
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
