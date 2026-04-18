"""Configuration constants: subreddits, search terms, date range, paths.

All tunable inputs for the sentiment tracker live here so the rest of
the pipeline reads like plain code. Bump ``PROMPT_VERSION`` whenever the
scoring rubric changes — cached scores tagged with an older version are
re-scored automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

DB_PATH = DATA_DIR / "sentiment.db"
CSV_PATH = OUTPUT_DIR / "weekly_aggregates.csv"
PNG_PATH = OUTPUT_DIR / "sentiment_chart.png"
HTML_PATH = OUTPUT_DIR / "sentiment_chart.html"
METHODOLOGY_PATH = OUTPUT_DIR / "methodology.md"

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Brand buckets
# ---------------------------------------------------------------------------

BRAND_POPMART = "popmart"
BRAND_FUNKO = "funko"

BRAND_DISPLAY = {
    BRAND_POPMART: "Pop Mart / Labubu",
    BRAND_FUNKO: "Funko Pop",
}


@dataclass(frozen=True)
class SubredditSource:
    """A subreddit to pull from, and whether posts must match a brand term."""

    name: str
    # If True, keep only posts whose title/body contains one of the search
    # terms for the relevant brand. If False, treat every post in that
    # subreddit as already on-topic for the brand.
    filter_by_term: bool


# Brand-specific subreddits: everything posted counts.
POPMART_SUBREDDITS = [
    SubredditSource("PopMartCollectors", filter_by_term=False),
    SubredditSource("Labubu", filter_by_term=False),
    SubredditSource("popmart", filter_by_term=False),
    # Cross-brand collector subs — keep only posts that mention Pop Mart terms.
    SubredditSource("blindboxes", filter_by_term=True),
    SubredditSource("Hellokittycollectibles", filter_by_term=True),
]

FUNKO_SUBREDDITS = [
    SubredditSource("funkopop", filter_by_term=False),
    SubredditSource("funko", filter_by_term=False),
    SubredditSource("funkopopdisplay", filter_by_term=False),
    SubredditSource("funkoswap", filter_by_term=False),
]

# Neutral cross-brand subreddits — must mention one of the brand terms;
# classified into whichever brand the matched term belongs to.
NEUTRAL_SUBREDDITS = [
    SubredditSource("collectibles", filter_by_term=True),
    SubredditSource("ActionFigures", filter_by_term=True),
]

# Search terms per brand. Case-insensitive match on title + selftext.
POPMART_TERMS = ["Labubu", "Pop Mart", "PopMart", "Skullpanda", "Molly", "Dimoo", "Hirono"]
FUNKO_TERMS = ["Funko", "Funko Pop", "Pop figure", "Loungefly"]

BRAND_TERMS = {
    BRAND_POPMART: POPMART_TERMS,
    BRAND_FUNKO: FUNKO_TERMS,
}

# ---------------------------------------------------------------------------
# Time window — April 2024 through "now". Keep "now" dynamic so re-runs
# automatically pick up new posts.
# ---------------------------------------------------------------------------

START_DATE = datetime(2024, 4, 1, tzinfo=timezone.utc)


def end_date() -> datetime:
    """Return the upper bound of the scrape window (now, UTC)."""
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Scrape caps
# ---------------------------------------------------------------------------

TARGET_POSTS_PER_BRAND = 300
MAX_POSTS_PER_BRAND = 500

# Per-subreddit Reddit search: ask for more than we need, then filter.
POSTS_PER_QUERY = 500

# Top-level comments per post: only collect if the post has this many upvotes.
COMMENT_POST_SCORE_MIN = 10
MAX_COMMENTS_PER_POST = 5

# ---------------------------------------------------------------------------
# LLM scoring
# ---------------------------------------------------------------------------

CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

# Bump this whenever the rubric in score_sentiment.py changes so old
# cached scores get re-run. Keep it short and sortable.
PROMPT_VERSION = "v1.0"

MAX_CONCURRENT_LLM_CALLS = 50
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 200

# Token-cost guardrail — if the pre-run estimate exceeds this, pause and
# ask the operator to confirm. Haiku list pricing (Apr 2026): $1 / MTok
# input, $5 / MTok output.
COST_WARN_USD = 20.0
HAIKU_INPUT_PRICE_PER_MTOK = 1.0
HAIKU_OUTPUT_PRICE_PER_MTOK = 5.0

# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

# Comments are noisier than posts; down-weight them relative to posts.
COMMENT_WEIGHT_FACTOR = 0.5

# Rolling-window length for the line chart (in weeks).
SMOOTHING_WINDOW_WEEKS = 4

# Statistical test: compare recent divergence against zero using this many
# trailing weeks.
DIVERGENCE_TEST_WINDOW_WEEKS = 8


def all_subreddits() -> list[str]:
    """Flat, deduplicated list of subreddit names that get touched."""
    names: list[str] = []
    for bucket in (POPMART_SUBREDDITS, FUNKO_SUBREDDITS, NEUTRAL_SUBREDDITS):
        for src in bucket:
            if src.name not in names:
                names.append(src.name)
    return names
