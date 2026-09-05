# ADR-001 — Every change accounts for dead and duplicate code

- **Status:** Accepted
- **Date:** 2026-09-05
- **Applies to:** every change to this repository

---

## Context

Sprint 12 opened with an audit comparing the git history against the running
system. The same defect kept turning up wearing different clothes:

| What | Built | Reached at runtime |
|---|---|---|
| `MilvusVectorStore` | Sprint 9, 25 tests | Superseded in Sprint 12; nothing constructed it |
| `MongoVectorStore` | Sprint 6 | `upsert` raised `NotImplementedError` |
| `ModelSelectorPort` | Sprint 8, ~30 tests | Zero implementers, ever |
| `MetricsCollector` | Sprint 8, 24 tests | Never constructed |
| `MongoQueryLogRepository` | Sprint 4 | Never constructed; docstring said "Used in production" |
| 5 Prometheus metrics | Sprints 7–9 | Never emitted — a permanent zero on `/metrics` |

None of this was low-quality code. It was well-written, well-tested, and
unreachable. That combination is worse than an obvious gap, because every
signal a reviewer normally trusts says the feature exists:

- **the tests pass** — they test the dead code directly, so they always will;
- **the package exports it** — `__init__.py` re-exported both dead vector
  stores, so an import sweep counted them as live;
- **the docstring asserts it** — one literally said "Used in production";
- **the dashboard shows a number** — a metric nothing emits reports `0`, which
  reads as *measured, and healthy*, not as *not measured*.

Two of those metrics had been zero for four sprints. Nobody noticed, because
noticing required asking a question about the whole repository, and a diff only
shows you one corner of it.

The duplication half is the same failure seen from the other side. Eight
modules each hand-rolled `t0 = time.perf_counter() ... (perf_counter() - t0) *
1000`. The one that reached Prometheus recorded **seconds** into a metric of its
own invention while the rest recorded nothing. Two spellings of one measurement
is how a dashboard ends up disagreeing with itself.

## Decision

**Every change accounts for what it makes redundant.** A change is not complete
when the new code works. It is complete when the code the new code replaced is
gone, and when the new code has not introduced a second way to do something the
codebase already does.

Concretely, before opening a PR:

1. **Is anything now unreachable?** If this change supersedes an
   implementation, delete it in the same PR. Not "later", not behind a
   deprecation comment. `git revert` is one command; dead code is forever.
2. **Is this a second way to do something?** If the codebase already has a
   helper, a metric, or a port for this, use it or replace it. Do not add a
   parallel one.
3. **Does anything reach the new code?** A class only its tests construct is
   not a feature. Wire it in the same PR, or do not merge it.
4. **Do the docstrings still describe reality?** "Used in production" must be
   true when written, and deleted when it stops being true.

### Deleting versus wiring

Both are valid answers; they are not interchangeable.

- **Delete** when the code is superseded, or when nothing can implement it —
  `MilvusVectorStore` had a working replacement; `ModelSelectorPort` had no
  implementers and never would.
- **Wire** when the capability is genuinely wanted and the only thing missing
  is the plumbing. Per-stage metrics were rebuilt rather than restored,
  because the original design required threading a collector object through
  four layers, which is precisely why nobody ever did.

What is **not** valid is leaving it. Code kept "in case we want it" carries the
full cost of maintenance and false confidence, and delivers none of the value.

## Enforcement

This is a test, not a checklist item. Checklists were what failed.

`src/tests/unit/test_no_dead_code.py` fails the build when:

| Guard | Catches |
|---|---|
| `TestEveryModuleIsReached` | A module imported only by its own tests, or only by an `__init__` re-export |
| `TestEveryMetricIsEmitted` | A metric in `prometheus_metrics.__all__` that no production module imports |
| `TestEveryStageIsTimed` | A `Stage` member declared but never passed to `stage_timer()` |
| `TestNoSecondWayToTimeAStage` | A pipeline module hand-rolling `perf_counter` instead of using `stage_timer()` |

Each guard was verified by mutation — a deliberate violation was introduced and
each guard failed on it. A guard that cannot fail is worth exactly as much as
the tests this ADR exists to prevent.

Each guard carries an **allowlist**, not a heuristic. `src/main.py` is an entry
point; the benchmarks time their own harness runs. An allowlist entry is a claim
a person made in a diff and can be argued with in review. A heuristic that
silently excuses whole categories is how the original problem survived an
import sweep in the first place.

### Adding to an allowlist

Legitimate. Add the entry **and the reason**, in the same commit as the code
that needs it. If the reason is hard to write, that is the finding.

## Consequences

**What gets better.** Dead code fails on the PR that creates it rather than
during an audit six sprints later. `/metrics` contains only series something
writes, so a flat line means the system is quiet, not that the metric is
fictional. There is one way to time a stage, so two panels cannot disagree.

**What it costs.** Deleting is now part of building, so some PRs are larger and
touch files the author did not otherwise intend to. Test suites shrink when
dead code goes — the Sprint 12 cleanup removed 52 tests, and a coverage number
that drops for this reason is an improvement.

**Where it does not reach.** These guards check *reachability*, not *usefulness*.
Code can be wired, emitted, and pointless. That still needs a human in review.
The guards remove the failure mode where nobody could have noticed.

**A caveat worth stating.** `TestEveryModuleIsReached` uses static imports. A
module reached only through a runtime string lookup — a plugin registry, an
entry-point table — will look dead to it. None exist today. If one is
introduced, allowlist it with that reason rather than weakening the guard.

## Related

- Per-stage latency and token metrics: `src/observability/stage_timer.py`
- Metric definitions: `src/observability/prometheus_metrics.py`
- Behavioural tests for the above: `src/tests/integration/test_stage_metrics.py`
