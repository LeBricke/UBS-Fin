"""Orchestrator: read -> score -> aggregate -> visualize."""

from __future__ import annotations

import sys
import time

import aggregate
import read_documents
import score_statements
import visualize


def _banner(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def main() -> int:
    start = time.time()

    _banner("Stage 1/4 — Read documents from data/transcripts/")
    try:
        read_documents.run()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"stage 1 failed: {exc}", file=sys.stderr)
        return 1

    _banner("Stage 2/4 — Score statements with Claude Haiku 4.5")
    try:
        score_statements.run()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"stage 2 failed: {exc}", file=sys.stderr)
        return 1

    _banner("Stage 3/4 — Aggregate per-period and per-half-year")
    try:
        aggregate.run()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"stage 3 failed: {exc}", file=sys.stderr)
        return 1

    _banner("Stage 4/4 — Render charts and methodology.md")
    try:
        visualize.run()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"stage 4 failed: {exc}", file=sys.stderr)
        return 1

    elapsed = time.time() - start
    _banner(f"Done in {elapsed:.1f}s")
    print("Outputs in output/:")
    print("  scored_by_period.csv    — per-period rollup")
    print("  scored_by_half.csv      — per-half-year rollup (charted)")
    print("  sentiment_chart.png     — confidence small-multiples (300 DPI)")
    print("  direction_chart.png     — direction small-multiples (300 DPI)")
    print("  methodology.md          — appendix-ready method note")
    return 0


if __name__ == "__main__":
    sys.exit(main())
