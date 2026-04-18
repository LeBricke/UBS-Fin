"""Phase 2: classify cached Reddit content with Claude Haiku 4.5.

Reads un-scored posts and comments from SQLite, sends them to the
Anthropic API concurrently (capped at ``MAX_CONCURRENT_LLM_CALLS``),
and upserts the results into ``sentiment_scores``.

Re-scoring strategy: a row is considered "already scored" only if its
``classifier_prompt_version`` matches the current ``PROMPT_VERSION`` in
config. If the rubric changes, bumping the version causes everything to
be re-scored on the next run — by design.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

import config
from scrape_reddit import open_db

# ---------------------------------------------------------------------------
# Prompts — keep in lockstep with PROMPT_VERSION in config.py.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a careful sentiment classifier for collectibles community posts.\n"
    "You score one post or comment at a time on a fixed -1/0/+1 rubric.\n"
    "You return only valid JSON. You do not editorialize or add commentary."
)

USER_PROMPT_TEMPLATE = """You are evaluating a Reddit post about {brand} from a collector community.

Score the OVERALL sentiment toward the {brand} brand or its products on this scale:
  +1 = clearly positive (excitement, recommendation, brand affection, defending the brand, sharing happy purchase)
   0 = neutral, mixed, informational, or off-topic for sentiment (e.g. "where can I buy", trade requests, factual questions, balanced takes)
  -1 = clearly negative (frustration, disappointment, complaints about quality/pricing/availability, regret, criticizing the brand, comparing unfavorably)

Also assign ONE primary topic tag and optionally ONE secondary tag, choosing from:
  - "quality" (build/materials/durability)
  - "pricing" (cost, value-for-money, price hikes)
  - "availability" (stock, scalpers, drops)
  - "design" (aesthetic, IP appeal, character love)
  - "community" (collector culture, social aspects)
  - "comparison" (explicitly vs other brands or other collectibles)
  - "fomo_or_hype" (urgency, viral, trending)
  - "fatigue" (oversaturation, lost interest, moving on)
  - "logistics" (shipping, packaging, customs)
  - "other"

Provide a confidence score 0.0-1.0 (how confident you are in the -1/0/+1 score) and a one-sentence reasoning.

Return ONLY this JSON, no other text:
{{
  "sentiment_score": <-1 | 0 | 1>,
  "confidence": <0.0-1.0>,
  "primary_topic": "<tag>",
  "secondary_topic": "<tag or null>",
  "reasoning": "<one sentence>"
}}

Post text:
---
{text}
---"""

BRAND_LABEL = {
    config.BRAND_POPMART: "Pop Mart/Labubu",
    config.BRAND_FUNKO: "Funko Pop",
}

# Truncate long selftext to keep token costs bounded. Haiku handles much
# more, but Reddit posts past ~2000 chars are usually repetitive.
MAX_INPUT_CHARS = 2000

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToScore:
    content_id: str
    content_type: str  # 'post' or 'comment'
    brand: str
    text: str


@dataclass
class ScoreResult:
    content_id: str
    content_type: str
    brand: str
    sentiment_score: int
    confidence: float
    primary_topic: str
    secondary_topic: str | None
    reasoning: str
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


def _load_unscored(conn: sqlite3.Connection) -> list[ToScore]:
    """Return every post + qualifying comment not yet scored at PROMPT_VERSION."""
    out: list[ToScore] = []

    post_rows = conn.execute(
        """
        SELECT p.id, p.brand, p.title, p.body
        FROM posts p
        WHERE NOT EXISTS (
            SELECT 1 FROM sentiment_scores s
            WHERE s.content_id = p.id
              AND s.classifier_prompt_version = ?
        )
        """,
        (config.PROMPT_VERSION,),
    ).fetchall()
    for row in post_rows:
        text = (row["title"] or "").strip()
        if row["body"]:
            text = f"{text}\n\n{row['body'].strip()}"
        text = text[:MAX_INPUT_CHARS]
        if text:
            out.append(ToScore(row["id"], "post", row["brand"], text))

    comment_rows = conn.execute(
        """
        SELECT c.id, c.body, p.brand
        FROM comments c
        JOIN posts p ON p.id = c.post_id
        WHERE NOT EXISTS (
            SELECT 1 FROM sentiment_scores s
            WHERE s.content_id = c.id
              AND s.classifier_prompt_version = ?
        )
        """,
        (config.PROMPT_VERSION,),
    ).fetchall()
    for row in comment_rows:
        body = (row["body"] or "").strip()
        if not body or body in {"[deleted]", "[removed]"}:
            continue
        out.append(ToScore(row["id"], "comment", row["brand"], body[:MAX_INPUT_CHARS]))

    return out


def _upsert_score(conn: sqlite3.Connection, result: ScoreResult) -> None:
    conn.execute(
        """
        INSERT INTO sentiment_scores
          (content_id, content_type, brand, sentiment_score,
           sentiment_confidence, primary_topic, secondary_topic,
           reasoning, classifier_model, classifier_prompt_version, scored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(content_id) DO UPDATE SET
          content_type = excluded.content_type,
          brand = excluded.brand,
          sentiment_score = excluded.sentiment_score,
          sentiment_confidence = excluded.sentiment_confidence,
          primary_topic = excluded.primary_topic,
          secondary_topic = excluded.secondary_topic,
          reasoning = excluded.reasoning,
          classifier_model = excluded.classifier_model,
          classifier_prompt_version = excluded.classifier_prompt_version,
          scored_at = excluded.scored_at
        """,
        (
            result.content_id,
            result.content_type,
            result.brand,
            result.sentiment_score,
            result.confidence,
            result.primary_topic,
            result.secondary_topic,
            result.reasoning,
            config.CLASSIFIER_MODEL,
            config.PROMPT_VERSION,
            time.time(),
        ),
    )


# ---------------------------------------------------------------------------
# Cost estimate & confirmation
# ---------------------------------------------------------------------------


def _estimate_cost_usd(items: list[ToScore]) -> float:
    """Rough cost estimate assuming ~4 chars per token for input.

    Output is capped at LLM_MAX_TOKENS and typically lands ~80 tokens.
    """
    prompt_overhead_chars = len(SYSTEM_PROMPT) + len(USER_PROMPT_TEMPLATE)
    total_input_tokens = 0
    for item in items:
        chars = len(item.text) + prompt_overhead_chars
        total_input_tokens += chars // 4
    # Assume average 80 output tokens (JSON stays compact).
    total_output_tokens = len(items) * 80

    input_cost = total_input_tokens / 1_000_000 * config.HAIKU_INPUT_PRICE_PER_MTOK
    output_cost = total_output_tokens / 1_000_000 * config.HAIKU_OUTPUT_PRICE_PER_MTOK
    return input_cost + output_cost


def _confirm_if_expensive(cost: float) -> bool:
    if cost <= config.COST_WARN_USD:
        return True
    print(f"WARNING: estimated cost ${cost:.2f} exceeds guard of "
          f"${config.COST_WARN_USD:.2f}.")
    ans = input("Proceed? [y/N]: ").strip().lower()
    return ans == "y"


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_VALID_TOPICS = {
    "quality", "pricing", "availability", "design", "community",
    "comparison", "fomo_or_hype", "fatigue", "logistics", "other",
}


def _parse_response(raw: str) -> dict[str, Any] | None:
    """Parse Claude's JSON reply. Returns None if unparseable."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = _JSON_RE.search(raw)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _normalize_result(
    item: ToScore,
    parsed: dict[str, Any] | None,
    usage_in: int,
    usage_out: int,
) -> ScoreResult:
    if parsed is None:
        return ScoreResult(
            content_id=item.content_id,
            content_type=item.content_type,
            brand=item.brand,
            sentiment_score=0,
            confidence=0.0,
            primary_topic="other",
            secondary_topic=None,
            reasoning="parse_error",
            input_tokens=usage_in,
            output_tokens=usage_out,
        )

    try:
        score = int(parsed.get("sentiment_score", 0))
    except (TypeError, ValueError):
        score = 0
    if score not in (-1, 0, 1):
        score = 0

    try:
        conf = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    primary = str(parsed.get("primary_topic") or "other").lower()
    if primary not in _VALID_TOPICS:
        primary = "other"

    secondary_raw = parsed.get("secondary_topic")
    if secondary_raw in (None, "null", ""):
        secondary: str | None = None
    else:
        secondary_str = str(secondary_raw).lower()
        secondary = secondary_str if secondary_str in _VALID_TOPICS else None

    reasoning = str(parsed.get("reasoning") or "").strip()[:500]

    return ScoreResult(
        content_id=item.content_id,
        content_type=item.content_type,
        brand=item.brand,
        sentiment_score=score,
        confidence=conf,
        primary_topic=primary,
        secondary_topic=secondary,
        reasoning=reasoning,
        input_tokens=usage_in,
        output_tokens=usage_out,
    )


async def _score_one(client, sem: asyncio.Semaphore, item: ToScore) -> ScoreResult:
    prompt = USER_PROMPT_TEMPLATE.format(brand=BRAND_LABEL[item.brand], text=item.text)
    async with sem:
        try:
            resp = await client.messages.create(
                model=config.CLASSIFIER_MODEL,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=config.LLM_MAX_TOKENS,
                temperature=config.LLM_TEMPERATURE,
            )
        except Exception as exc:  # pragma: no cover — network / auth / model
            print(f"  [warn] API error on {item.content_id}: {exc}")
            return _normalize_result(item, None, 0, 0)

    try:
        raw_text = resp.content[0].text  # type: ignore[index]
    except (IndexError, AttributeError):
        raw_text = ""
    in_tokens = getattr(resp.usage, "input_tokens", 0) if resp.usage else 0
    out_tokens = getattr(resp.usage, "output_tokens", 0) if resp.usage else 0

    parsed = _parse_response(raw_text)
    return _normalize_result(item, parsed, in_tokens, out_tokens)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _build_client():
    from anthropic import AsyncAnthropic  # lazy import

    load_dotenv(config.PROJECT_ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Missing ANTHROPIC_API_KEY. Copy .env.example to .env and set it."
        )
    # max_retries=5 so transient 429/529 responses are retried with the
    # SDK's built-in exponential backoff.
    return AsyncAnthropic(max_retries=5)


async def _score_all(items: list[ToScore]) -> tuple[list[ScoreResult], int, int]:
    client = _build_client()
    sem = asyncio.Semaphore(config.MAX_CONCURRENT_LLM_CALLS)

    tasks = [asyncio.create_task(_score_one(client, sem, item)) for item in items]
    results: list[ScoreResult] = []
    total_in = total_out = 0
    for i, coro in enumerate(asyncio.as_completed(tasks), start=1):
        result = await coro
        results.append(result)
        total_in += result.input_tokens
        total_out += result.output_tokens
        if i % 100 == 0 or i == len(tasks):
            print(f"  scored {i}/{len(tasks)}")
    return results, total_in, total_out


def run() -> None:
    """Score all un-scored content currently in the DB."""
    conn = open_db()
    items = _load_unscored(conn)
    if not items:
        print("Nothing to score — all cached content already has a score at "
              f"prompt_version={config.PROMPT_VERSION}.")
        conn.close()
        return

    print(f"Scoring {len(items)} items ({sum(1 for i in items if i.content_type == 'post')} posts, "
          f"{sum(1 for i in items if i.content_type == 'comment')} comments) "
          f"at prompt_version={config.PROMPT_VERSION}")

    est = _estimate_cost_usd(items)
    print(f"Pre-run cost estimate: ${est:.2f} "
          f"(Haiku 4.5 at ${config.HAIKU_INPUT_PRICE_PER_MTOK}/MTok input, "
          f"${config.HAIKU_OUTPUT_PRICE_PER_MTOK}/MTok output)")
    if not _confirm_if_expensive(est):
        print("Aborted by user.")
        conn.close()
        return

    results, total_in, total_out = asyncio.run(_score_all(items))

    for result in results:
        _upsert_score(conn, result)
    conn.commit()
    conn.close()

    actual_cost = (
        total_in / 1_000_000 * config.HAIKU_INPUT_PRICE_PER_MTOK
        + total_out / 1_000_000 * config.HAIKU_OUTPUT_PRICE_PER_MTOK
    )
    print(f"Done. Wrote {len(results)} scores. "
          f"Usage: {total_in:,} input + {total_out:,} output tokens. "
          f"Actual cost: ${actual_cost:.2f}")


if __name__ == "__main__":
    try:
        run()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
