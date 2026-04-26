"""Stage 2: score each statement with Claude Haiku 4.5.

Reads ``data/statements.csv``, sends one API call per statement,
parses the JSON reply, and writes ``data/scored.csv`` with added
columns ``topic, confidence, direction, rationale``.

Statements where the reply is malformed twice in a row are skipped
(logged to stdout). Statements where the topic is "none" are still
written to the CSV; ``aggregate.py`` filters them out downstream.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
STATEMENTS_CSV = PROJECT_ROOT / "data" / "statements.csv"
SCORED_CSV = PROJECT_ROOT / "data" / "scored.csv"

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 200

SYSTEM_PROMPT = (
    "You are an equity research analyst scoring sentiment in corporate disclosures."
)

USER_PROMPT = """Statement from {company} ({period}):
"{text}"

Categorize this statement. Return ONLY valid JSON with no other text:
{{
  "topic": "overseas_expansion" | "margin_trajectory" | "ip_performance" | "channel_strategy" | "capital_allocation" | "none",
  "confidence": <integer from -2 to +2>,
  "direction": <integer from -2 to +2>,
  "rationale": "<one sentence>"
}}

Definitions:
- topic: pick THE single most relevant topic, or "none" if the statement is not substantively about any of these topics (e.g. boilerplate, financial statement line items, disclaimers)
- confidence: -2=defensive/uncertain, -1=cautious, 0=neutral, +1=positive, +2=highly confident. Score management's tone about the topic, not the underlying facts.
- direction: -2=trend deteriorating, -1=softening, 0=stable, +1=improving, +2=strongly improving. Score what management says about the trend direction.
- rationale: one sentence explaining your scores."""

VALID_TOPICS = {
    "overseas_expansion", "margin_trajectory", "ip_performance",
    "channel_strategy", "capital_allocation", "none",
}

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _build_client():
    from anthropic import Anthropic  # lazy import

    load_dotenv(PROJECT_ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Missing ANTHROPIC_API_KEY. Copy .env.example to .env and set it."
        )
    return Anthropic(max_retries=2)


def _parse_json(raw: str) -> dict | None:
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


def _clamp_int(value, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(lo, min(hi, n))


def _normalize(parsed: dict | None) -> dict | None:
    """Return a dict with the four scored fields, or None if unusable."""
    if not isinstance(parsed, dict):
        return None
    topic = str(parsed.get("topic") or "").strip().lower()
    if topic not in VALID_TOPICS:
        return None
    return {
        "topic": topic,
        "confidence": _clamp_int(parsed.get("confidence"), -2, 2),
        "direction": _clamp_int(parsed.get("direction"), -2, 2),
        "rationale": str(parsed.get("rationale") or "").strip()[:500],
    }


def _score_one(client, company: str, period: str, text: str) -> dict | None:
    """One API call plus one retry. Returns normalized dict or None on failure."""
    prompt = USER_PROMPT.format(company=company, period=period, text=text)
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=MODEL,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
                temperature=0,
            )
        except Exception as exc:  # pragma: no cover — network/auth
            last_error = exc
            continue

        try:
            raw = resp.content[0].text  # type: ignore[index]
        except (IndexError, AttributeError):
            raw = ""
        normalized = _normalize(_parse_json(raw))
        if normalized is not None:
            return normalized

    if last_error is not None:
        print(f"  [skip] API error after retry: {last_error}")
    else:
        print("  [skip] malformed JSON after retry")
    return None


def run() -> int:
    """Score every statement. Returns number of scored rows written."""
    if not STATEMENTS_CSV.exists():
        raise FileNotFoundError(
            f"{STATEMENTS_CSV} not found. Run read_documents.py first."
        )

    with STATEMENTS_CSV.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    total = len(rows)
    if total == 0:
        print("No statements to score.")
        return 0

    client = _build_client()

    SCORED_CSV.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with SCORED_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "company", "period", "statement_index", "text",
            "topic", "confidence", "direction", "rationale",
        ])
        for i, row in enumerate(rows, start=1):
            scored = _score_one(client, row["company"], row["period"], row["text"])
            if scored is None:
                continue
            writer.writerow([
                row["company"], row["period"], row["statement_index"], row["text"],
                scored["topic"], scored["confidence"],
                scored["direction"], scored["rationale"],
            ])
            written += 1
            if i % 10 == 0 or i == total:
                print(f"  Scored {i}/{total} statements")

    print(f"Stage 2 done. {written}/{total} statements scored, written to "
          f"{SCORED_CSV.relative_to(PROJECT_ROOT)}")
    return written


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
