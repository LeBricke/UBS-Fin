"""Stage 3: aggregate scored statements to per-period and per-half tables.

Reads ``data/scored.csv``, drops topic=none rows, and writes two CSVs
under ``output/``:

- ``scored_by_period.csv`` — one row per (company, period, topic)
- ``scored_by_half.csv``   — one row per (company, reporting_half, topic)

The ``reporting_half`` column maps Funko's Q1-Q4 onto half-year buckets
so Pop Mart's half-year filings and Funko's quarterly calls sit on the
same x-axis.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
SCORED_CSV = PROJECT_ROOT / "data" / "scored.csv"
BY_PERIOD_CSV = PROJECT_ROOT / "output" / "scored_by_period.csv"
BY_HALF_CSV = PROJECT_ROOT / "output" / "scored_by_half.csv"


def _to_reporting_half(period: str) -> str:
    """popmart H1/H2 stay; funko Q1/Q2 -> H1, Q3/Q4 -> H2 of same year."""
    year = period[:4]
    tag = period[4:]
    if tag in ("H1", "H2"):
        return period
    if tag in ("Q1", "Q2"):
        return f"{year}H1"
    if tag in ("Q3", "Q4"):
        return f"{year}H2"
    # Shouldn't happen if read_documents.py accepted it.
    return period


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Produce per-period and per-half DataFrames, write both to CSV."""
    if not SCORED_CSV.exists():
        raise FileNotFoundError(
            f"{SCORED_CSV} not found. Run score_statements.py first."
        )

    df = pd.read_csv(SCORED_CSV)
    df = df[df["topic"] != "none"].copy()
    if df.empty:
        raise RuntimeError("No on-topic statements to aggregate.")

    df["reporting_half"] = df["period"].apply(_to_reporting_half)

    by_period = (
        df.groupby(["company", "period", "topic"], as_index=False)
          .agg(
              mean_confidence=("confidence", "mean"),
              mean_direction=("direction", "mean"),
              statement_count=("confidence", "size"),
          )
    )

    by_half = (
        df.groupby(["company", "reporting_half", "topic"], as_index=False)
          .agg(
              mean_confidence=("confidence", "mean"),
              mean_direction=("direction", "mean"),
              statement_count=("confidence", "size"),
          )
    )

    BY_PERIOD_CSV.parent.mkdir(parents=True, exist_ok=True)
    by_period.to_csv(BY_PERIOD_CSV, index=False)
    by_half.to_csv(BY_HALF_CSV, index=False)
    print(f"Stage 3 done. Wrote {len(by_period)} rows to "
          f"{BY_PERIOD_CSV.relative_to(PROJECT_ROOT)} and "
          f"{len(by_half)} rows to {BY_HALF_CSV.relative_to(PROJECT_ROOT)}")
    return by_period, by_half


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
