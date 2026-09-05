"""Reconcile the chunk store against the vector store.

Thin entry point. Everything it knows how to do lives in ReembedAssetsUseCase;
this resolves the wiring from the DI container, parses flags, and prints.

    python -m src.infrastructure.cli.reembed --dry-run
    python -m src.infrastructure.cli.reembed
    python -m src.infrastructure.cli.reembed --tenant ferza

Exit codes, so it can gate a deploy:

    0  every asset that could be repaired is consistent
    1  something is still broken — an embed failed, or --dry-run found work
    2  the container could not be built (no Mongo, no embedding service, …)
"""
from __future__ import annotations

import argparse
import sys

from src.domain.models.embedding_consistency import AssetEmbedState, ReembedReport
from src.infrastructure.di.factory import build_worker_container
from src.observability.structured_logger import get_logger
from src.use_cases.reembed_assets import ReembedAssetsUseCase

logger = get_logger(__name__)

_SYMBOL = {
    AssetEmbedState.CONSISTENT: "ok  ",
    AssetEmbedState.MISSING:    "MISS",
    AssetEmbedState.MISMATCHED: "DIFF",
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reembed",
        description="Re-embed assets whose vectors do not match their chunks.",
    )
    parser.add_argument(
        "--tenant",
        default=None,
        help="restrict to one tenant (default: every tenant)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing anything",
    )
    return parser.parse_args(argv)


def _print_report(report: ReembedReport) -> None:
    print()
    print(f"{'state':<6} {'tenant':<12} {'asset':<38} chunks  vectors")
    print("-" * 76)
    for asset in report.scanned:
        print(
            f"{_SYMBOL[asset.state]:<6} "
            f"{asset.ref.tenant_id:<12} "
            f"{asset.ref.asset_id:<38} "
            f"{asset.chunk_count:>6}  {asset.vector_count:>7}"
        )

    counts = {state: len(report.of_state(state)) for state in AssetEmbedState}
    print("-" * 76)
    print(
        f"scanned {len(report.scanned)}   "
        f"consistent {counts[AssetEmbedState.CONSISTENT]}   "
        f"missing {counts[AssetEmbedState.MISSING]}   "
        f"mismatched {counts[AssetEmbedState.MISMATCHED]}"
    )

    if report.dry_run:
        todo = sum(1 for a in report.scanned if a.needs_reembedding)
        print(f"\ndry run — {todo} asset(s) would be re-embedded, nothing written")
    elif report.repaired:
        ok = len(report.repaired) - len(report.failures)
        print(f"\nre-embedded {ok} asset(s), {report.vectors_written} vector(s) written")
        for failure in report.failures:
            print(f"  FAILED {failure.ref.tenant_id}/{failure.ref.asset_id}: {failure.error}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        container = build_worker_container()
    except Exception as exc:  # noqa: BLE001 — a wiring failure is a usage error, not a crash
        print(f"could not build the container: {exc}", file=sys.stderr)
        return 2

    use_case = ReembedAssetsUseCase(
        chunk_store=container.get("chunk_store"),
        vector_store=container.get("vector_store"),
        embed_uc=container.get("embed_use_case"),
    )
    report = use_case.execute(tenant_id=args.tenant, dry_run=args.dry_run)
    _print_report(report)

    if args.dry_run:
        return 0 if not any(a.needs_reembedding for a in report.scanned) else 1
    return 0 if report.is_consistent else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
