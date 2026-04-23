"""Phase 3: weekly aggregation, engagement weighting, divergence metric.

Reads ``posts``, ``comments``, and ``sentiment_scores`` from SQLite and
writes ``output/weekly_aggregates.csv`` with one row per
``(week_start, brand)``. Also returns an in-memory DataFrame and a
divergence statistical-test result for the methodology note.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

import pandas as pd

import config
from scrape_reddit import open_db

# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def _load_joined(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return one row per scored item with brand, timestamp, upvotes, topic.

    Schema of the result:
      content_id, content_type, brand, created_utc, score (reddit upvotes),
      sentiment_score, primary_topic
    """
    post_sql = """
        SELECT
          p.id              AS content_id,
          'post'            AS content_type,
          p.brand           AS brand,
          p.created_utc     AS created_utc,
          p.score           AS reddit_score,
          s.sentiment_score AS sentiment_score,
          s.primary_topic   AS primary_topic
        FROM posts p
        JOIN sentiment_scores s
          ON s.content_id = p.id
         AND s.classifier_prompt_version = ?
    """
    comment_sql = """
        SELECT
          c.id              AS content_id,
          'comment'         AS content_type,
          p.brand           AS brand,
          c.created_utc     AS created_utc,
          c.score           AS reddit_score,
          s.sentiment_score AS sentiment_score,
          s.primary_topic   AS primary_topic
        FROM comments c
        JOIN posts p ON p.id = c.post_id
        JOIN sentiment_scores s
          ON s.content_id = c.id
         AND s.classifier_prompt_version = ?
    """
    posts_df = pd.read_sql_query(post_sql, conn, params=(config.PROMPT_VERSION,))
    comments_df = pd.read_sql_query(comment_sql, conn, params=(config.PROMPT_VERSION,))
    return pd.concat([posts_df, comments_df], ignore_index=True)


# ---------------------------------------------------------------------------
# Weighting
# ---------------------------------------------------------------------------


def _apply_weights(df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``weight`` column: log(1 + max(0, score)) for posts, halved for comments."""
    safe_score = df["reddit_score"].fillna(0).clip(lower=0)
    # log1p(score) stays non-negative; even a score-0 post gets a small base
    # weight so zero-upvote items aren't completely dropped.
    base = (safe_score.apply(lambda s: math.log1p(float(s))) + 0.1)
    factor = df["content_type"].map(
        lambda t: config.COMMENT_WEIGHT_FACTOR if t == "comment" else 1.0
    )
    out = df.copy()
    out["weight"] = base * factor
    return out


# ---------------------------------------------------------------------------
# Weekly rollup
# ---------------------------------------------------------------------------


def _to_week_start(series: pd.Series) -> pd.Series:
    """Map a unix-timestamp series to the Monday of its ISO week (UTC)."""
    dt = pd.to_datetime(series, unit="s", utc=True)
    # Drop tz before period conversion (pandas can't put a period on a
    # tz-aware series). The underlying instant doesn't move.
    naive = dt.dt.tz_convert("UTC").dt.tz_localize(None)
    period = naive.dt.to_period("W-SUN")  # week ends Sunday -> starts Monday
    return period.dt.start_time


def _weekly_rollup(df: pd.DataFrame) -> pd.DataFrame:
    """Weighted weekly sentiment + post/comment counts + top 3 topics."""
    df = df.copy()
    df["week_start"] = _to_week_start(df["created_utc"])

    # Weighted average sentiment per (brand, week)
    df["weighted_contribution"] = df["sentiment_score"] * df["weight"]

    grouped = df.groupby(["brand", "week_start"], sort=True)
    agg = grouped.agg(
        weighted_sum=("weighted_contribution", "sum"),
        total_weight=("weight", "sum"),
        post_count=("content_type", lambda s: int((s == "post").sum())),
        comment_count=("content_type", lambda s: int((s == "comment").sum())),
    ).reset_index()

    safe_weight = agg["total_weight"].where(agg["total_weight"] > 0)
    agg["weighted_sentiment"] = (agg["weighted_sum"] / safe_weight).astype(float)

    # Top-3 primary topics per (brand, week), ranked by total weight.
    topic_ranks: list[dict] = []
    for (brand, week), sub in df.groupby(["brand", "week_start"]):
        topic_totals = (
            sub.groupby("primary_topic")["weight"].sum().sort_values(ascending=False)
        )
        top3 = list(topic_totals.head(3).index)
        while len(top3) < 3:
            top3.append(None)
        topic_ranks.append({
            "brand": brand,
            "week_start": week,
            "top_topic_1": top3[0],
            "top_topic_2": top3[1],
            "top_topic_3": top3[2],
        })
    topics_df = pd.DataFrame(topic_ranks)
    agg = agg.merge(topics_df, on=["brand", "week_start"], how="left")

    # 4-week rolling smooth, within each brand.
    agg = agg.sort_values(["brand", "week_start"]).reset_index(drop=True)
    agg["sentiment_4wk_smoothed"] = (
        agg.groupby("brand")["weighted_sentiment"]
        .transform(lambda s: s.rolling(
            window=config.SMOOTHING_WINDOW_WEEKS, min_periods=1
        ).mean())
    )

    return agg[[
        "week_start", "brand", "weighted_sentiment", "post_count",
        "comment_count", "total_weight", "top_topic_1", "top_topic_2",
        "top_topic_3", "sentiment_4wk_smoothed",
    ]]


# ---------------------------------------------------------------------------
# Divergence + statistical test
# ---------------------------------------------------------------------------


@dataclass
class DivergenceTest:
    recent_window_weeks: int
    recent_mean_divergence: float
    t_statistic: float
    p_value: float
    n: int

    def sentence(self) -> str:
        sig = "statistically different from zero" if self.p_value < 0.05 else "not statistically different from zero"
        return (
            f"Over the most recent {self.recent_window_weeks} weeks, the "
            f"Pop Mart minus Funko sentiment divergence averaged "
            f"{self.recent_mean_divergence:+.3f} (n={self.n}, "
            f"t={self.t_statistic:.2f}, p={self.p_value:.3f}) — {sig}."
        )


def _divergence_series(weekly: pd.DataFrame) -> pd.DataFrame:
    """Pivot to wide and compute divergence = popmart - funko per week."""
    wide = weekly.pivot(
        index="week_start", columns="brand", values="weighted_sentiment"
    )
    # The pair trade we're evidencing is long Pop Mart / short Funko;
    # divergence > 0 == the thesis is showing up in the data.
    if "popmart" in wide.columns and "funko" in wide.columns:
        wide["divergence"] = wide["popmart"] - wide["funko"]
    else:
        wide["divergence"] = float("nan")
    return wide.reset_index()


def _divergence_test(wide: pd.DataFrame) -> DivergenceTest | None:
    """One-sample t-test on the most recent N weeks of divergence vs zero."""
    from scipy import stats  # lazy import

    tail = wide.dropna(subset=["divergence"]).tail(
        config.DIVERGENCE_TEST_WINDOW_WEEKS
    )
    if len(tail) < 3:
        return None
    values = tail["divergence"].to_numpy(dtype=float)
    result = stats.ttest_1samp(values, popmean=0.0)
    return DivergenceTest(
        recent_window_weeks=len(tail),
        recent_mean_divergence=float(values.mean()),
        t_statistic=float(result.statistic),
        p_value=float(result.pvalue),
        n=int(len(tail)),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass
class AnalysisResult:
    weekly: pd.DataFrame           # long-format, one row per (week, brand)
    wide: pd.DataFrame             # week x brand matrix + divergence column
    test: DivergenceTest | None    # None if not enough data
    total_scored: int
    total_by_brand: dict[str, int]


def run() -> AnalysisResult:
    """Aggregate and write the weekly CSV. Returns an AnalysisResult."""
    conn = open_db()
    try:
        raw = _load_joined(conn)
    finally:
        conn.close()

    if raw.empty:
        raise RuntimeError(
            "No scored content found in DB. Run scrape_reddit.py and "
            "score_sentiment.py first."
        )

    weighted = _apply_weights(raw)
    weekly = _weekly_rollup(weighted)
    wide = _divergence_series(weekly)
    test = _divergence_test(wide)

    # Write CSV with stable column order and ISO date strings.
    out = weekly.copy()
    out["week_start"] = pd.to_datetime(out["week_start"]).dt.strftime("%Y-%m-%d")
    out.to_csv(config.CSV_PATH, index=False)
    print(f"Wrote {len(out):,} weekly rows to {config.CSV_PATH}")
    if test is not None:
        print(test.sentence())

    totals = raw.groupby("brand").size().to_dict()
    return AnalysisResult(
        weekly=weekly,
        wide=wide,
        test=test,
        total_scored=int(len(raw)),
        total_by_brand={k: int(v) for k, v in totals.items()},
    )


if __name__ == "__main__":
    run()
