# Cross-Brand Reddit Sentiment Tracker

Evidence tool for one slide in TAG Capital's UBS Finance Challenge pitch:
**long Pop Mart (9992.HK), short Funko (FNKO US).**

It answers a single research question:

> Across the past ~18 months, how has Reddit-based collector sentiment
> evolved for Labubu / Pop Mart versus Funko Pop in Western collector
> communities, and when did the divergence become visible?

Output is a deck-ready PNG chart, an interactive HTML version, the
underlying weekly CSV, and an auto-generated `methodology.md`.

## Setup

The tool is Reddit-only by design (TikTok and X were ruled out on
access/cost grounds — see `output/methodology.md` after a run).

### 1. Install dependencies

With `uv` (preferred):

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

Or plain `pip`:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get a Reddit API credential

1. Sign in at <https://www.reddit.com/prefs/apps>.
2. Click **"are you a developer? create an app..."** at the bottom.
3. Pick type **"script"**. Name it anything (e.g. `tag-capital-sentiment`).
   Redirect URI: `http://localhost:8080` (unused for script apps).
4. The app page shows a 14-character **client ID** under the app name
   and a **client secret**. Copy both.
5. Your **user agent** should be something identifiable, e.g.
   `tag-capital-sentiment/0.1 by u/your_reddit_username`.

### 3. Get an Anthropic API key

Go to <https://console.anthropic.com/settings/keys> and generate a key.

### 4. Configure `.env`

```bash
cp .env.example .env
# then edit .env and fill in all four values
```

## Running

Full pipeline:

```bash
python run_all.py
```

This runs four phases in order:

1. **Scrape** — pull posts from Reddit into `data/sentiment.db`.
2. **Score** — classify un-scored posts via Claude Haiku 4.5.
3. **Analyze** — weekly rollups with engagement weighting.
4. **Visualize** — write PNG, HTML, CSV, and `methodology.md` into `output/`.

The SQLite DB caches both scraped content and sentiment scores, so a
second run finishes in under a minute (nothing new to scrape or score).

You can also run any phase on its own — useful while tweaking the chart:

```bash
python scrape_reddit.py
python score_sentiment.py
python analyze.py
python visualize.py
```

## Refreshing on April 28

Before the final run for the submission:

```bash
# 1. Pull the latest posts from the time window
python scrape_reddit.py

# 2. Score only the new ones (existing scores are cached)
python score_sentiment.py

# 3. Re-aggregate and re-render
python analyze.py
python visualize.py
```

Then drop `output/sentiment_chart.png` into the deck and paste the
relevant paragraphs from `output/methodology.md` into the appendix.

## What's in `output/`

- `sentiment_chart.png` — deck-ready 300 DPI PNG, TAG Capital palette.
- `sentiment_chart.html` — interactive Plotly version for exploration.
- `weekly_aggregates.csv` — the underlying weekly data.
- `methodology.md` — date range, subreddits, search terms, post counts,
  classifier version, statistical test, and honest limitations.

## What this tool is not

- Not a dashboard, not a scheduled service, not a web app.
- Not multi-language — English Reddit only.
- Not a behavior signal — it measures **opinion**, not purchases.

See `output/methodology.md` after a run for the full limitations list.
