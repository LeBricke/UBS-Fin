"""Phase 1: pull posts and top comments from Reddit into SQLite.

Public entry point is :func:`run`. It is idempotent: already-scraped
post and comment IDs are ignored via ``INSERT OR IGNORE``, so re-running
only fetches new content.

Reddit's search API is rate-limited (~60 requests/minute for a script
app). We do very few searches per run so this isn't a bottleneck, but
backoff on 429 is still handled by PRAW internally.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Iterable

from dotenv import load_dotenv

import config

# PRAW is imported lazily inside run() so that `import scrape_reddit`
# during tests doesn't require Reddit creds.

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    author TEXT,
    created_utc REAL NOT NULL,
    score INTEGER NOT NULL,
    num_comments INTEGER NOT NULL,
    url TEXT,
    matched_term TEXT,
    scraped_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT,
    created_utc REAL NOT NULL,
    score INTEGER NOT NULL,
    FOREIGN KEY (post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
    content_id TEXT PRIMARY KEY,
    content_type TEXT NOT NULL,
    brand TEXT NOT NULL,
    sentiment_score INTEGER NOT NULL,
    sentiment_confidence REAL,
    primary_topic TEXT,
    secondary_topic TEXT,
    reasoning TEXT,
    classifier_model TEXT NOT NULL,
    classifier_prompt_version TEXT NOT NULL,
    scored_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_brand_date ON posts(brand, created_utc);
CREATE INDEX IF NOT EXISTS idx_scores_brand ON sentiment_scores(brand);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist. Safe to call repeatedly."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def open_db() -> sqlite3.Connection:
    """Open the project SQLite DB and ensure the schema exists."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _term_matches(text: str, terms: Iterable[str]) -> str | None:
    """Return the first search term found in ``text`` (case-insensitive), or None."""
    lower = text.lower()
    for term in terms:
        if term.lower() in lower:
            return term
    return None


def _in_window(created_utc: float) -> bool:
    start = config.START_DATE.timestamp()
    end = config.end_date().timestamp()
    return start <= created_utc <= end


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------


@dataclass
class ScrapeCounts:
    new_posts: int = 0
    new_comments: int = 0


def _upsert_post(
    conn: sqlite3.Connection,
    submission,  # praw Submission
    brand: str,
    matched_term: str | None,
) -> bool:
    """Insert a post if unseen. Returns True if a new row was inserted."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO posts
          (id, brand, subreddit, title, body, author, created_utc,
           score, num_comments, url, matched_term, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            submission.id,
            brand,
            str(submission.subreddit),
            submission.title or "",
            submission.selftext or "",
            str(submission.author) if submission.author else None,
            float(submission.created_utc),
            int(submission.score or 0),
            int(submission.num_comments or 0),
            f"https://reddit.com{submission.permalink}",
            matched_term,
            time.time(),
        ),
    )
    return cur.rowcount > 0


def _upsert_comment(conn: sqlite3.Connection, comment, post_id: str) -> bool:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO comments
          (id, post_id, body, author, created_utc, score)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            comment.id,
            post_id,
            comment.body or "",
            str(comment.author) if comment.author else None,
            float(comment.created_utc),
            int(comment.score or 0),
        ),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Reddit client
# ---------------------------------------------------------------------------


def _build_reddit_client():
    """Return a configured PRAW Reddit instance. Reads creds from .env."""
    import praw  # lazy import

    load_dotenv(config.PROJECT_ROOT / ".env")

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT")
    if not all((client_id, client_secret, user_agent)):
        raise RuntimeError(
            "Missing Reddit credentials. Copy .env.example to .env and fill "
            "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT."
        )
    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        check_for_async=False,
    )


# ---------------------------------------------------------------------------
# Search strategy
# ---------------------------------------------------------------------------


def _iter_candidate_submissions(reddit, source, terms: list[str]):
    """Yield submissions from a subreddit that match our date window.

    For brand-specific subs (``filter_by_term=False``), we iterate
    ``subreddit.new(limit=POSTS_PER_QUERY)``: cheapest and most complete
    within Reddit's 1000-item listing cap.

    For cross-brand subs, we run Reddit's own search for each term; this
    is less complete but the only way to pull matching posts efficiently.
    """
    sub = reddit.subreddit(source.name)

    if not source.filter_by_term:
        for submission in sub.new(limit=config.POSTS_PER_QUERY):
            yield submission
        return

    seen_ids: set[str] = set()
    for term in terms:
        try:
            results = sub.search(term, sort="new", time_filter="all",
                                 limit=config.POSTS_PER_QUERY)
        except Exception as exc:  # pragma: no cover — Reddit search can flake
            print(f"  [warn] search {source.name!r} term={term!r} failed: {exc}")
            continue
        for submission in results:
            if submission.id in seen_ids:
                continue
            seen_ids.add(submission.id)
            yield submission


def _scrape_brand(
    conn: sqlite3.Connection,
    reddit,
    brand: str,
    sources: list[config.SubredditSource],
    neutral_sources: list[config.SubredditSource],
    counts: ScrapeCounts,
) -> None:
    """Fetch posts for one brand bucket and insert them."""
    terms = config.BRAND_TERMS[brand]
    to_process = list(sources) + list(neutral_sources)
    # If we already have enough posts for this brand in-DB and within the
    # window, we can stop early on subsequent runs.
    brand_count = conn.execute(
        "SELECT COUNT(*) AS n FROM posts WHERE brand = ?", (brand,)
    ).fetchone()["n"]
    print(f"[{brand}] currently {brand_count} posts in DB; target {config.TARGET_POSTS_PER_BRAND}")

    for source in to_process:
        print(f"[{brand}] scanning r/{source.name} (filter_by_term={source.filter_by_term})")
        for submission in _iter_candidate_submissions(reddit, source, terms):
            if not _in_window(float(submission.created_utc)):
                continue

            haystack = f"{submission.title}\n{submission.selftext or ''}"
            matched = _term_matches(haystack, terms)

            # Brand-specific subs: keep even without a term match.
            # Cross-brand (neutral + filter_by_term) subs: require a match.
            if source.filter_by_term and matched is None:
                continue

            inserted = _upsert_post(conn, submission, brand, matched)
            if inserted:
                counts.new_posts += 1

            # Collect top-level comments if the post is popular enough.
            if int(submission.score or 0) >= config.COMMENT_POST_SCORE_MIN:
                try:
                    submission.comments.replace_more(limit=0)
                except Exception as exc:  # pragma: no cover
                    print(f"  [warn] replace_more failed on {submission.id}: {exc}")
                    continue
                top_comments = sorted(
                    submission.comments,
                    key=lambda c: int(getattr(c, "score", 0) or 0),
                    reverse=True,
                )[: config.MAX_COMMENTS_PER_POST]
                for comment in top_comments:
                    if _upsert_comment(conn, comment, submission.id):
                        counts.new_comments += 1

            # Cap total posts per brand so we don't blow the budget.
            current = conn.execute(
                "SELECT COUNT(*) AS n FROM posts WHERE brand = ?", (brand,)
            ).fetchone()["n"]
            if current >= config.MAX_POSTS_PER_BRAND:
                print(f"[{brand}] hit MAX_POSTS_PER_BRAND ({current}); stopping early")
                conn.commit()
                return

        conn.commit()


def run() -> ScrapeCounts:
    """Scrape Reddit into the SQLite DB. Returns counts of new rows inserted."""
    conn = open_db()
    reddit = _build_reddit_client()
    counts = ScrapeCounts()

    try:
        _scrape_brand(
            conn, reddit,
            brand=config.BRAND_POPMART,
            sources=config.POPMART_SUBREDDITS,
            neutral_sources=config.NEUTRAL_SUBREDDITS,
            counts=counts,
        )
        _scrape_brand(
            conn, reddit,
            brand=config.BRAND_FUNKO,
            sources=config.FUNKO_SUBREDDITS,
            neutral_sources=config.NEUTRAL_SUBREDDITS,
            counts=counts,
        )
    finally:
        conn.commit()

    # Final summary
    totals = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM posts) AS posts,
          (SELECT COUNT(*) FROM comments) AS comments
        """
    ).fetchone()
    print(
        f"Scraped {counts.new_posts} new posts, {counts.new_comments} new comments. "
        f"Total in DB: {totals['posts']} posts, {totals['comments']} comments."
    )
    conn.close()
    return counts


if __name__ == "__main__":
    try:
        run()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
