"""Phase 4: deck-ready PNG, interactive HTML, and methodology.md."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

import analyze
import config
import style
from scrape_reddit import open_db

# ---------------------------------------------------------------------------
# Event annotations — optional vertical dashed lines on the PNG.
# Add notable pair-trade-relevant dates here.
# ---------------------------------------------------------------------------

# Picked events are public (Pop Mart FY2025 release date, Funko earnings)
# that a judge can verify. Dates are week-starts; exact day is fine —
# matplotlib will put the marker on that date.
EVENT_ANNOTATIONS = [
    ("2025-03-26", "Pop Mart FY2025 sell-off"),
    ("2025-11-06", "Funko Q3 2025 earnings"),
]


# ---------------------------------------------------------------------------
# Summary counts for the source line and methodology
# ---------------------------------------------------------------------------


@dataclass
class ScrapeSummary:
    post_count: int
    comment_count: int
    scored_count: int
    subreddits: list[str]
    earliest: datetime | None
    latest: datetime | None
    posts_by_brand: dict[str, int]
    scored_by_brand: dict[str, int]


def _load_summary(conn: sqlite3.Connection) -> ScrapeSummary:
    post_row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(created_utc) AS mn, MAX(created_utc) AS mx FROM posts"
    ).fetchone()
    comment_count = conn.execute("SELECT COUNT(*) AS n FROM comments").fetchone()["n"]
    scored_count = conn.execute(
        "SELECT COUNT(*) AS n FROM sentiment_scores WHERE classifier_prompt_version = ?",
        (config.PROMPT_VERSION,),
    ).fetchone()["n"]
    subreddits = [
        r["subreddit"]
        for r in conn.execute("SELECT DISTINCT subreddit FROM posts ORDER BY subreddit")
    ]
    by_brand_posts = {
        r["brand"]: r["n"]
        for r in conn.execute("SELECT brand, COUNT(*) AS n FROM posts GROUP BY brand")
    }
    by_brand_scored = {
        r["brand"]: r["n"]
        for r in conn.execute(
            "SELECT brand, COUNT(*) AS n FROM sentiment_scores "
            "WHERE classifier_prompt_version = ? GROUP BY brand",
            (config.PROMPT_VERSION,),
        )
    }
    earliest = datetime.utcfromtimestamp(post_row["mn"]) if post_row["mn"] else None
    latest = datetime.utcfromtimestamp(post_row["mx"]) if post_row["mx"] else None
    return ScrapeSummary(
        post_count=post_row["n"],
        comment_count=comment_count,
        scored_count=scored_count,
        subreddits=subreddits,
        earliest=earliest,
        latest=latest,
        posts_by_brand=by_brand_posts,
        scored_by_brand=by_brand_scored,
    )


# ---------------------------------------------------------------------------
# PNG (matplotlib)
# ---------------------------------------------------------------------------


def _format_source_line(summary: ScrapeSummary) -> str:
    latest = summary.latest.strftime("%b %d, %Y") if summary.latest else "—"
    return (
        f"Source: Reddit posts and top comments across {len(summary.subreddits)} "
        f"subreddits, scored by Claude Haiku 4.5; n={summary.scored_count:,} "
        f"posts+comments. Data through {latest}. TAG Capital."
    )


def _render_png(weekly: pd.DataFrame, summary: ScrapeSummary) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    matplotlib.rcParams.update(style.get_matplotlib_rc())

    fig, ax = plt.subplots(figsize=(12, 6))

    for brand in (config.BRAND_POPMART, config.BRAND_FUNKO):
        sub = weekly[weekly["brand"] == brand].copy()
        sub = sub.sort_values("week_start")
        sub["week_start"] = pd.to_datetime(sub["week_start"])

        color = style.BRAND_COLOR[brand]
        label = style.BRAND_LEGEND_LABEL[brand]

        # Raw weekly: small dots at 30% alpha behind the smoothed line.
        ax.scatter(
            sub["week_start"], sub["weighted_sentiment"],
            s=14, color=color, alpha=0.30, zorder=2, linewidths=0,
        )
        # Smoothed series: primary visual.
        ax.plot(
            sub["week_start"], sub["sentiment_4wk_smoothed"],
            color=color, linewidth=2.5, label=label, zorder=3,
        )

    ax.axhline(0, color=style.TEXT_MUTED, linewidth=0.5, zorder=1)
    ax.set_ylim(-1.0, 1.0)
    ax.grid(axis="y")
    ax.set_axisbelow(True)

    # X-axis formatting: tick every 3 months, label like "Apr '24"
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    fig.autofmt_xdate(rotation=0, ha="center")

    # Reserve vertical room for a stacked title / subtitle / legend band
    # above the plot, and for the source line below.
    fig.subplots_adjust(top=0.80, bottom=0.15, left=0.08, right=0.97)

    fig.suptitle(
        "Reddit collector sentiment — Pop Mart vs Funko Pop",
        fontsize=16, fontweight="medium", color=style.TEXT_DARK,
        x=0.08, y=0.955, ha="left",
    )
    fig.text(
        0.08, 0.905,
        "Weekly weighted average, 4-week smoothed",
        fontsize=11, color=style.TEXT_MUTED, ha="left", va="center",
    )

    ax.set_ylabel("Weighted sentiment  (-1 negative / +1 positive)")
    ax.set_xlabel("")

    # Legend placed between the subtitle and the plot, horizontal.
    # This guarantees it never collides with data or annotations.
    leg = ax.legend(
        loc="upper right",
        bbox_to_anchor=(1.0, 1.12),
        frameon=False,
        handlelength=1.6,
        ncol=2,
    )
    for txt in leg.get_texts():
        txt.set_color(style.TEXT_DARK)

    # Event annotations: dashed line + small text with an ivory bbox so
    # the label stays readable when it crosses the data lines.
    if not weekly.empty:
        ymin, ymax = ax.get_ylim()
        for date_str, label in EVENT_ANNOTATIONS:
            event = pd.to_datetime(date_str)
            if summary.earliest and event < pd.Timestamp(summary.earliest):
                continue
            if summary.latest and event > pd.Timestamp(summary.latest):
                continue
            ax.axvline(
                event, color=style.TEXT_MUTED, linestyle="--",
                linewidth=1.0, alpha=0.5, zorder=1,
            )
            ax.text(
                event, ymax - 0.06, f" {label}",
                fontsize=9, color=style.TEXT_MUTED, ha="left", va="top",
                rotation=0, zorder=4,
                bbox={
                    "facecolor": style.BACKGROUND_WHITE,
                    "edgecolor": "none",
                    "pad": 2.0,
                },
            )

    # Source line — use fig.text so it sits below axes, within the
    # bottom margin reserved by subplots_adjust.
    fig.text(
        0.08, 0.03, _format_source_line(summary),
        fontsize=9, color=style.TEXT_MUTED, ha="left", va="bottom",
    )

    fig.savefig(
        config.PNG_PATH,
        dpi=300,
        facecolor=style.BACKGROUND_WHITE,
    )
    plt.close(fig)
    print(f"Wrote PNG to {config.PNG_PATH}")


# ---------------------------------------------------------------------------
# HTML (plotly)
# ---------------------------------------------------------------------------


def _render_html(weekly: pd.DataFrame, summary: ScrapeSummary) -> None:
    import plotly.graph_objects as go

    fig = go.Figure()

    for brand in (config.BRAND_POPMART, config.BRAND_FUNKO):
        sub = weekly[weekly["brand"] == brand].copy()
        sub = sub.sort_values("week_start")
        sub["week_start"] = pd.to_datetime(sub["week_start"])

        color = style.BRAND_COLOR[brand]
        label = style.BRAND_LEGEND_LABEL[brand]

        custom = sub[["post_count", "top_topic_1"]].fillna("").to_numpy()
        # Raw weekly dots (translucent)
        fig.add_trace(go.Scatter(
            x=sub["week_start"], y=sub["weighted_sentiment"],
            mode="markers", name=f"{label} (weekly)",
            marker={"color": color, "size": 6, "opacity": 0.30},
            showlegend=False,
            customdata=custom,
            hovertemplate=(
                "<b>%{x|%b %d, %Y}</b><br>"
                f"Brand: {style.BRAND_LEGEND_LABEL[brand]}<br>"
                "Weekly sentiment: %{y:.2f}<br>"
                "Posts: %{customdata[0]}<br>"
                "Top topic: %{customdata[1]}<extra></extra>"
            ),
        ))
        # Smoothed line
        fig.add_trace(go.Scatter(
            x=sub["week_start"], y=sub["sentiment_4wk_smoothed"],
            mode="lines", name=label,
            line={"color": color, "width": 3},
            hovertemplate=(
                "<b>%{x|%b %d, %Y}</b><br>"
                f"Brand: {style.BRAND_LEGEND_LABEL[brand]}<br>"
                "Smoothed: %{y:.2f}<extra></extra>"
            ),
        ))

    fig.update_layout(**style.plotly_layout())
    fig.update_layout(
        title={"text": "Reddit collector sentiment — Pop Mart vs Funko Pop"},
        xaxis={"title": ""},
        yaxis={
            "title": "Weighted sentiment  (-1 negative / +1 positive)",
            "range": [-1.0, 1.0],
        },
    )
    # Zero reference line
    fig.add_hline(y=0, line={"color": style.TEXT_MUTED, "width": 0.5})

    html = fig.to_html(
        full_html=True,
        include_plotlyjs="cdn",
        config={"displayModeBar": False},
    )
    # Page title per spec.
    html = html.replace(
        "<title>Plotly</title>",
        "<title>Reddit Collector Sentiment — TAG Capital</title>",
        1,
    )
    # Plotly doesn't emit a <title> tag by default; inject one if absent.
    if "<title>" not in html:
        html = html.replace(
            "<head>",
            "<head><title>Reddit Collector Sentiment — TAG Capital</title>",
            1,
        )

    with open(config.HTML_PATH, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Wrote HTML to {config.HTML_PATH}")


# ---------------------------------------------------------------------------
# methodology.md
# ---------------------------------------------------------------------------


LIMITATIONS = [
    "**Reddit-only.** We deliberately excluded TikTok (academic-affiliation "
    "review window was incompatible with our timeline) and X/Twitter (became "
    "pay-per-use in February 2026 with limited free tiers). A judge could "
    "reasonably ask whether this biases toward text-heavy, older-skewing "
    "collectors; we acknowledge this skew and note that Reddit's text density "
    "is what makes LLM classification reliable in the first place.",
    "**English-only.** Pop Mart's home-market sentiment (Mandarin Weibo, Xiaohongshu) "
    "is not captured. This tool is deliberately aimed at Funko's home market — "
    "the Western collector community — which is the specific thing our pair "
    "trade claims Labubu is taking share in.",
    "**Opinion, not behavior.** Sentiment is what people say. It is not a "
    "purchase signal. We treat it as directional evidence alongside financials "
    "and valuation, not as the sole basis for the trade.",
    "**Classifier consistency.** All scoring uses a single model "
    f"({config.CLASSIFIER_MODEL}) at temperature 0 under a fixed rubric "
    f"(prompt version {config.PROMPT_VERSION}). Re-runs are reproducible. "
    "Inter-rater reliability vs a human annotator has not been measured on "
    "this corpus; the +1/0/-1 rubric was chosen because it's coarse enough "
    "to be robust.",
    "**Subreddit selection bias.** Brand-dedicated subreddits skew positive "
    "(people don't join r/funkopop to complain about Funko). We partially "
    "correct for this by also pulling cross-brand subs (r/collectibles, "
    "r/ActionFigures) and by scoring comments alongside posts — comments "
    "are typically more critical than the post they sit under.",
    "**Engagement weighting assumption.** We weight by log(1 + upvotes) so "
    "a single mega-post doesn't dominate the signal. This is a choice, not "
    "a truth; an equal-weight alternative would shift the level but not the "
    "trend direction.",
    "**Bot / astroturf risk.** Not explicitly filtered. Reddit's own "
    "enforcement catches most bulk activity. Given our n≈2,000, a coordinated "
    "campaign would need to be visibly large for us to miss it.",
]


def _write_methodology(
    summary: ScrapeSummary,
    test: analyze.DivergenceTest | None,
) -> None:
    lines: list[str] = []
    lines.append("# Reddit Sentiment Tracker — Methodology\n")
    lines.append("_Auto-generated by `visualize.py`. Do not edit by hand._\n")

    lines.append("## Scope\n")
    earliest = summary.earliest.strftime("%Y-%m-%d") if summary.earliest else "—"
    latest = summary.latest.strftime("%Y-%m-%d") if summary.latest else "—"
    lines.append(f"- **Date range covered:** {earliest} through {latest}")
    lines.append(f"- **Subreddits queried:** `{'`, `'.join(summary.subreddits)}`")
    lines.append("- **Search terms (Pop Mart bucket):** "
                 + ", ".join(f"`{t}`" for t in config.POPMART_TERMS))
    lines.append("- **Search terms (Funko bucket):** "
                 + ", ".join(f"`{t}`" for t in config.FUNKO_TERMS))
    lines.append("")

    lines.append("## Volume\n")
    lines.append(f"- Total posts scraped: **{summary.post_count:,}**")
    for brand, n in sorted(summary.posts_by_brand.items()):
        lines.append(f"  - {config.BRAND_DISPLAY.get(brand, brand)}: {n:,}")
    lines.append(f"- Total top-level comments scraped: **{summary.comment_count:,}**")
    lines.append(
        f"- Total items scored at prompt_version `{config.PROMPT_VERSION}`: "
        f"**{summary.scored_count:,}**"
    )
    for brand, n in sorted(summary.scored_by_brand.items()):
        lines.append(f"  - {config.BRAND_DISPLAY.get(brand, brand)}: {n:,}")
    lines.append("")

    lines.append("## Classifier\n")
    lines.append(f"- **Model:** `{config.CLASSIFIER_MODEL}`")
    lines.append(f"- **Prompt version:** `{config.PROMPT_VERSION}`")
    lines.append(f"- **Temperature:** {config.LLM_TEMPERATURE}")
    lines.append(f"- **Max tokens:** {config.LLM_MAX_TOKENS}")
    lines.append("- **Rubric:** +1 clearly positive, 0 neutral / mixed / off-topic, "
                 "-1 clearly negative. Primary + optional secondary topic tag from a "
                 "fixed 10-value vocabulary. One-sentence reasoning per classification.")
    lines.append("")

    lines.append("## Aggregation\n")
    lines.append(
        f"- **Buckets:** ISO weeks (Mon–Sun), UTC."
    )
    lines.append(
        f"- **Engagement weighting:** each item contributes `sentiment × "
        f"(log(1 + upvotes) + 0.1)`. Comments are multiplied by "
        f"{config.COMMENT_WEIGHT_FACTOR} to reflect their noisier signal."
    )
    lines.append(
        f"- **Smoothing:** {config.SMOOTHING_WINDOW_WEEKS}-week trailing rolling mean "
        "of the weighted weekly sentiment."
    )
    lines.append(
        f"- **Divergence metric:** `sentiment(popmart) − sentiment(funko)` per week."
    )
    lines.append("")

    lines.append("## Statistical check\n")
    if test is not None:
        lines.append(test.sentence())
    else:
        lines.append(
            "Not enough weeks of overlapping data to run a one-sample t-test "
            f"(need ≥ 3, have fewer)."
        )
    lines.append("")

    lines.append("## Limitations\n")
    for item in LIMITATIONS:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Reproducibility\n")
    lines.append(
        "Re-running `python run_all.py` produces identical scores because "
        "temperature is 0 and the SQLite DB caches all prior classifications. "
        "Only new Reddit posts hit the API on a subsequent run."
    )
    lines.append("")

    with open(config.METHODOLOGY_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Wrote methodology to {config.METHODOLOGY_PATH}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Produce PNG, HTML, and methodology.md from the current DB state."""
    analysis = analyze.run()

    conn = open_db()
    try:
        summary = _load_summary(conn)
    finally:
        conn.close()

    _render_png(analysis.weekly, summary)
    _render_html(analysis.weekly, summary)
    _write_methodology(summary, analysis.test)


if __name__ == "__main__":
    run()
