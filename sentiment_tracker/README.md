# Management Commentary Sentiment Scorer

Evidence tool for one slide in TAG Capital's UBS Finance Challenge pitch:
**long Pop Mart (9992.HK), short Funko (FNKO).**

Given pre-collected earnings filings (Pop Mart, 6 HKEX results announcements)
and earnings-call transcripts (Funko, 6 quarterly calls), it scores every
substantive paragraph with Claude Haiku 4.5 across five thesis-relevant
topics, aggregates into half-year buckets, and renders two small-multiples
charts plus a methodology note ready to drop into a deck and appendix.

## What this tool does

1. Reads documents in `data/transcripts/`.
2. Splits each into paragraphs and calls Claude Haiku 4.5 on each one with a
   fixed rubric (topic + confidence + direction, each an integer in [-2, +2]).
3. Aggregates to per-period and per-half-year rollups.
4. Draws a 2×3 small-multiples chart (one panel per topic) and a methodology
   markdown file.

Total runtime on 12 documents: under 10 minutes. Total Anthropic cost:
under $2 at current Haiku 4.5 pricing.

## Setup

### 1. Install dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Set your Anthropic API key

```bash
cp .env.example .env
# then edit .env and paste your key
```

Key lives at <https://console.anthropic.com/settings/keys>.

### 3. Drop documents into `data/transcripts/`

Filenames must match `<company>_<YYYY><H1|H2|Q1-Q4>.<ext>`. Anything that
doesn't match is logged and skipped.

Expected files:

| File | Company | Period | Type |
|---|---|---|---|
| `popmart_2023H1.pdf` | Pop Mart | H1 2023 | HKEX interim results |
| `popmart_2023H2.pdf` | Pop Mart | H2 2023 | HKEX annual results |
| `popmart_2024H1.pdf` | Pop Mart | H1 2024 | HKEX interim results |
| `popmart_2024H2.pdf` | Pop Mart | H2 2024 | HKEX annual results |
| `popmart_2025H1.pdf` | Pop Mart | H1 2025 | HKEX interim results |
| `popmart_2025H2.pdf` | Pop Mart | H2 2025 | HKEX annual results |
| `funko_2024Q3.txt` | Funko | Q3 2024 | earnings call transcript |
| `funko_2024Q4.txt` | Funko | Q4 2024 | earnings call transcript |
| `funko_2025Q1.txt` | Funko | Q1 2025 | earnings call transcript |
| `funko_2025Q2.txt` | Funko | Q2 2025 | earnings call transcript |
| `funko_2025Q3.txt` | Funko | Q3 2025 | earnings call transcript |
| `funko_2025Q4.txt` | Funko | Q4 2025 | earnings call transcript |

Documents are not tracked in git.

## Running

```bash
python run_all.py
```

Each stage is also runnable on its own while iterating:

```bash
python read_documents.py     # data/transcripts/ -> data/statements.csv
python score_statements.py   # data/statements.csv -> data/scored.csv (Anthropic API)
python aggregate.py          # data/scored.csv -> output/scored_by_*.csv
python visualize.py          # the CSVs -> PNGs + methodology.md
```

## Outputs

All files below are regenerated on each run and are gitignored.

| Path | What it is |
|---|---|
| `data/statements.csv` | Every extracted paragraph, one row each |
| `data/scored.csv` | Same rows plus Claude's topic / confidence / direction / rationale |
| `output/scored_by_period.csv` | Means by (company, period, topic) |
| `output/scored_by_half.csv` | Means by (company, half-year, topic) — charted |
| `output/sentiment_chart.png` | Confidence small-multiples chart, 300 DPI |
| `output/direction_chart.png` | Direction small-multiples chart, 300 DPI |
| `output/methodology.md` | Appendix-ready methodology with prompt, counts, limitations |

Paste `sentiment_chart.png` into the deck. Paste the relevant sections of
`methodology.md` into the appendix.
