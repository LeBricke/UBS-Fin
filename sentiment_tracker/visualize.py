"""Stage 4: small-multiples charts + methodology.md.

Reads ``output/scored_by_half.csv`` and writes:

- ``output/sentiment_chart.png`` — management confidence by topic
- ``output/direction_chart.png`` — trend direction by topic
- ``output/methodology.md``       — auto-generated doc for the appendix
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
BY_HALF_CSV = PROJECT_ROOT / "output" / "scored_by_half.csv"
SCORED_CSV = PROJECT_ROOT / "data" / "scored.csv"
TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "transcripts"

SENTIMENT_PNG = PROJECT_ROOT / "output" / "sentiment_chart.png"
DIRECTION_PNG = PROJECT_ROOT / "output" / "direction_chart.png"
METHODOLOGY_MD = PROJECT_ROOT / "output" / "methodology.md"

COMPANY_COLOR = {"popmart": "#2ca02c", "funko": "#d62728"}
COMPANY_LABEL = {"popmart": "Pop Mart", "funko": "Funko"}

TOPIC_ORDER = [
    "overseas_expansion",
    "margin_trajectory",
    "ip_performance",
    "channel_strategy",
    "capital_allocation",
]

TOPIC_LABEL = {
    "overseas_expansion": "Overseas expansion",
    "margin_trajectory": "Margin trajectory",
    "ip_performance": "IP performance",
    "channel_strategy": "Channel strategy",
    "capital_allocation": "Capital allocation",
}

TOPIC_DEFINITION = {
    "overseas_expansion": "Non-home-market growth, store openings, regional momentum.",
    "margin_trajectory": "Gross / operating margin direction and what's driving it.",
    "ip_performance": "How individual IP lines (Labubu, Skullpanda; Disney, Marvel, etc.) are selling and resonating.",
    "channel_strategy": "Distribution mix — own stores vs wholesale, DTC, online, specialty.",
    "capital_allocation": "Buybacks, dividends, capex, debt repayment, M&A posture.",
}

HALF_ORDER = ["2023H1", "2023H2", "2024H1", "2024H2", "2025H1", "2025H2"]


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------


def _render_grid(
    df: pd.DataFrame, value_col: str, title: str, subtitle: str, out_path: Path,
) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), sharey=True)
    axes = axes.flatten()

    for idx, topic in enumerate(TOPIC_ORDER):
        ax = axes[idx]
        sub = df[df["topic"] == topic]
        for company in ("popmart", "funko"):
            s = sub[sub["company"] == company].set_index("reporting_half")
            if s.empty:
                continue
            # Reindex to the full half ordering so gaps are real gaps, not
            # re-connected lines across missing halves.
            s = s.reindex(HALF_ORDER)
            ax.plot(
                HALF_ORDER, s[value_col].to_numpy(),
                marker="o", linewidth=2.0,
                color=COMPANY_COLOR[company],
                label=COMPANY_LABEL[company],
            )
        ax.set_title(TOPIC_LABEL[topic], fontsize=11)
        ax.set_ylim(-2.1, 2.1)
        ax.axhline(0, linestyle="--", color="#888888", linewidth=0.8)
        ax.grid(axis="y", alpha=0.2)
        ax.tick_params(axis="x", rotation=45, labelsize=9)
        ax.tick_params(axis="y", labelsize=9)

    # Sixth panel: legend + axis explanation
    legend_ax = axes[5]
    legend_ax.axis("off")
    for company in ("popmart", "funko"):
        legend_ax.plot([], [], marker="o", linewidth=2.0,
                       color=COMPANY_COLOR[company], label=COMPANY_LABEL[company])
    legend_ax.legend(loc="upper left", frameon=False, fontsize=12)
    legend_ax.text(
        0.0, 0.55,
        "Y-axis: mean score across\nall scored statements\nfor that topic and half.",
        transform=legend_ax.transAxes, fontsize=10, color="#333333", va="top",
    )
    legend_ax.text(
        0.0, 0.20,
        f"Range: -2 to +2.\nDashed line = 0 (neutral).",
        transform=legend_ax.transAxes, fontsize=10, color="#333333", va="top",
    )

    fig.suptitle(title, fontsize=15, fontweight="medium", x=0.08, ha="left", y=0.98)
    fig.text(0.08, 0.94, subtitle, fontsize=11, color="#555555", ha="left")
    fig.supylabel(value_col.replace("_", " ").title(), x=0.015, fontsize=10)

    fig.tight_layout(rect=[0.02, 0.01, 1, 0.92])
    fig.savefig(out_path, dpi=300, facecolor="white")
    plt.close(fig)
    print(f"  wrote {out_path.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# methodology.md
# ---------------------------------------------------------------------------


_PROMPT_QUOTE = '''System: You are an equity research analyst scoring sentiment in corporate disclosures.

User: Statement from {company} ({period}):
"{text}"

Categorize this statement. Return ONLY valid JSON with no other text:
{
  "topic": "overseas_expansion" | "margin_trajectory" | "ip_performance" | "channel_strategy" | "capital_allocation" | "none",
  "confidence": <integer from -2 to +2>,
  "direction": <integer from -2 to +2>,
  "rationale": "<one sentence>"
}

Definitions:
- topic: pick THE single most relevant topic, or "none" if the statement is not substantively about any of these topics.
- confidence: -2 defensive/uncertain ... +2 highly confident. Tone about the topic, not the facts.
- direction: -2 deteriorating ... +2 strongly improving. Trend direction management describes.
- rationale: one sentence explaining your scores.'''


def _document_description(name: str) -> str:
    lower = name.lower()
    if lower.startswith("popmart_"):
        return "Pop Mart interim / annual results announcement (HKEX filing, written)."
    if lower.startswith("funko_"):
        return "Funko quarterly earnings call transcript (prepared remarks + Q&A, spoken)."
    return "Unrecognized document."


def _write_methodology(scored: pd.DataFrame) -> None:
    lines: list[str] = []
    lines.append("# Management Commentary Sentiment — Methodology\n")
    lines.append("_Auto-generated by `visualize.py`. Do not edit by hand._\n")

    lines.append("## Purpose\n")
    lines.append(
        "This tool supports TAG Capital's pair trade (long Pop Mart 9992.HK, "
        "short Funko FNKO) by showing how each company's management has been "
        "talking about five thesis-relevant topics over the last ~2.5 years. "
        "The intended output is a deck slide: judges should see divergent "
        "trajectories on the topics that matter for the trade.\n"
    )

    lines.append("## Source documents\n")
    if TRANSCRIPTS_DIR.exists():
        docs = sorted(p.name for p in TRANSCRIPTS_DIR.iterdir()
                      if p.is_file() and p.suffix.lower() in {".pdf", ".txt"})
        if docs:
            for name in docs:
                lines.append(f"- `{name}` — {_document_description(name)}")
        else:
            lines.append("- _(no documents found)_")
    else:
        lines.append("- _(data/transcripts/ does not exist)_")
    lines.append("")

    lines.append("## Document asymmetry\n")
    lines.append(
        "Pop Mart files formal written interim and annual results announcements "
        "with the Hong Kong Stock Exchange. Funko releases spoken earnings-call "
        "transcripts. Written filings run more cautious and compliance-shaped; "
        "spoken transcripts swing more with the CEO's rhetoric of the day. "
        "**We control for this by measuring within-company change over time "
        "rather than absolute cross-company sentiment levels.** The core "
        "evidence for the thesis is the trajectory divergence, not the level "
        "gap at any single point.\n"
    )

    lines.append("## Method\n")
    lines.append(
        "1. Parse company and reporting period from each filename "
        "(`<company>_<YYYY><H1|H2|Q1-Q4>.<ext>`).\n"
        "2. Extract text (pdfplumber for PDFs, plain read for .txt), split on "
        "blank lines, keep paragraphs 100–2000 chars long.\n"
        "3. Score each paragraph with Claude Haiku 4.5 "
        "(`claude-haiku-4-5-20251001`, temperature 0) against the rubric below.\n"
        "4. Drop paragraphs classified as `none`; take per-topic means within "
        "each (company, half-year) bucket.\n"
        "5. Render small-multiples line charts: one panel per topic, two lines "
        "(Pop Mart vs Funko), x-axis = half-year, y-axis = mean score."
    )
    lines.append("")

    lines.append("## Topic taxonomy\n")
    for topic in TOPIC_ORDER:
        lines.append(f"- **{TOPIC_LABEL[topic]}** (`{topic}`) — {TOPIC_DEFINITION[topic]}")
    lines.append("- **none** — boilerplate, financial statement line items, disclaimers, or anything not substantively about the five topics above. Dropped before aggregation.")
    lines.append("")

    lines.append("## Prompt\n")
    lines.append("```")
    lines.append(_PROMPT_QUOTE)
    lines.append("```")
    lines.append("")

    lines.append("## Scored-statement counts\n")
    # Cross-tab of (company, period) × topic
    pivot = (
        scored[scored["topic"] != "none"]
        .groupby(["company", "period"])
        .size()
        .reset_index(name="scored_paragraphs")
        .sort_values(["company", "period"])
    )
    lines.append("| Company | Period | Scored paragraphs (excl. `none`) |")
    lines.append("|---|---|---:|")
    for _, row in pivot.iterrows():
        lines.append(f"| {row['company']} | {row['period']} | {row['scored_paragraphs']} |")

    # Also show topic distribution
    lines.append("")
    lines.append("### Topic distribution across all scored paragraphs\n")
    topic_counts = scored["topic"].value_counts()
    for topic, n in topic_counts.items():
        lines.append(f"- `{topic}`: {n}")
    lines.append("")

    lines.append("## Limitations\n")
    lines.append(
        "- **English only.** Pop Mart publishes its HKEX filings in English "
        "but its domestic investor communication is in Mandarin; that's "
        "outside the corpus.\n"
        "- **One primary topic per statement.** A paragraph that mixes "
        "overseas momentum and margin discussion gets force-picked into one "
        "bucket. Secondary signal is lost by design.\n"
        "- **LLM scoring variance.** Even at temperature 0, minor prompt "
        "rewordings would shift individual scores. Trajectories are robust; "
        "individual data points are not.\n"
        "- **Written vs spoken asymmetry.** See the section above. Level "
        "comparisons between companies should be treated as suggestive, not "
        "proof.\n"
        "- **Paragraph split is coarse.** Blank-line splitting works well on "
        "call transcripts, less perfectly on PDF-extracted filings where the "
        "text flow isn't always well-formed."
    )
    lines.append("")

    METHODOLOGY_MD.parent.mkdir(parents=True, exist_ok=True)
    METHODOLOGY_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {METHODOLOGY_MD.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    if not BY_HALF_CSV.exists():
        raise FileNotFoundError(
            f"{BY_HALF_CSV} not found. Run aggregate.py first."
        )
    if not SCORED_CSV.exists():
        raise FileNotFoundError(
            f"{SCORED_CSV} not found. Run score_statements.py first."
        )

    by_half = pd.read_csv(BY_HALF_CSV)
    scored = pd.read_csv(SCORED_CSV)

    _render_grid(
        by_half,
        value_col="mean_confidence",
        title="Management confidence trajectory: Pop Mart vs Funko",
        subtitle="Claude Haiku sentiment scoring of earnings disclosures, 2023H1 – 2025H2",
        out_path=SENTIMENT_PNG,
    )
    _render_grid(
        by_half,
        value_col="mean_direction",
        title="Management-described trend direction: Pop Mart vs Funko",
        subtitle="Claude Haiku direction scoring of earnings disclosures, 2023H1 – 2025H2",
        out_path=DIRECTION_PNG,
    )
    _write_methodology(scored)
    print("Stage 4 done.")


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
