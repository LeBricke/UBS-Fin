"""Orchestrator: run scrape -> score -> analyze -> visualize.

All four phases are idempotent. A second run with no new Reddit
content finishes in under a minute: scraping still checks Reddit for
new posts, but scoring and the cheap analyze/visualize phases do
nothing unscored.
"""

from __future__ import annotations

import sys
import time

import analyze
import scrape_reddit
import score_sentiment
import visualize


def _banner(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    start = time.time()

    _banner("Phase 1/4 — Scrape Reddit")
    try:
        scrape_reddit.run()
    except RuntimeError as exc:
        print(f"scrape failed: {exc}", file=sys.stderr)
        return 1

    _banner("Phase 2/4 — Score sentiment with Claude Haiku 4.5")
    try:
        score_sentiment.run()
    except RuntimeError as exc:
        print(f"scoring failed: {exc}", file=sys.stderr)
        return 1

    _banner("Phase 3/4 — Aggregate weekly")
    try:
        analyze.run()
    except RuntimeError as exc:
        print(f"analysis failed: {exc}", file=sys.stderr)
        return 1

    _banner("Phase 4/4 — Render chart, HTML, methodology")
    visualize.run()

    elapsed = time.time() - start
    _banner(f"Done in {elapsed:.1f}s")
    print("Outputs:")
    print("  output/sentiment_chart.png      (deck-ready, 300 DPI)")
    print("  output/sentiment_chart.html     (interactive Plotly)")
    print("  output/weekly_aggregates.csv    (underlying data)")
    print("  output/methodology.md           (scope, stats, limitations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
