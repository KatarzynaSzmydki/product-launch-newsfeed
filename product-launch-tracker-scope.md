# Tech Product Launch Tracker — Project Scope

## 1. Overview

Build an application that monitors news sources for major tech product launch
announcements, corroborates them across multiple sources before treating them
as confirmed, and generates a one-page brief per launch. The brief combines a
synthesized summary of the launch (from news coverage) with a factual stock
snapshot for the launching company (current price + trailing 12-month
performance).

This is a portfolio project. Priorities, in order: (1) correctness and honest
framing of any data presented, (2) clean architecture that's easy to explain
in an interview, (3) a polished-looking output. It does not need to scale to
production traffic.

## 2. Explicit non-goals (read before building)

- **No stock price prediction or forecasting of any kind.** The application
  reports historical/current data only — current price, 1-year % change,
  52-week high/low. It never generates a forward-looking price target,
  "expected reaction," or buy/sell signal.
- **No causal claims connecting news to stock moves.** The launch summary and
  the stock snapshot are presented side by side as independent sections. The
  generated text must not imply the stock moved *because of* the launch
  unless that's explicitly sourced from a cited analyst reaction — and even
  then it should be attributed to that source's opinion, not stated as fact.
- **Not investment advice.** Every generated brief should carry a visible
  disclaimer to that effect.
- Not trying to beat professional/algorithmic traders on speed. Polling
  every 10–15 minutes is fine; this is not a low-latency trading system.

## 3. Core pipeline

### 3.1 Monitoring layer
- Poll for tech product launch news on a schedule (every 10–15 min is fine).
- Primary source: a news API (NewsAPI.org, GNews, or Bing News Search —
  pick one with a usable free tier). Google News RSS as a secondary/backup
  signal.
- Config-driven list of tracked companies/tickers (e.g. a `companies.yaml`
  or `companies.json` with company name, stock ticker, and optional
  product-line keywords like "iPhone", "Pixel", "Copilot").
- Search query per company: company name + product-launch keywords
  ("unveils", "launches", "announces", "reveals") to reduce noise.

### 3.2 Corroboration / confirmation layer
- Do not treat a single article as a confirmed launch. Require
  corroboration from at least 2 independent sources before generating a
  brief, OR a single hit from a tier-1 source (the company's own press
  release/IR page, or a wire service like AP/Reuters).
- Maintain a simple source-trust tier (wire service / major outlet /
  tabloid / blog) used only to decide confirmation threshold, not to
  filter content out of the summary.
- Log every trigger event (what fired, which sources, timestamp,
  confirmed/pending status) so false positives can be reviewed and query
  rules tuned later.
- Add a "pending confirmation" state. A launch sitting in this state should
  not auto-generate a brief. (A manual approve step, even just a CLI
  command or a flag flip in a small admin view, is enough for a portfolio
  build — full human-in-the-loop UI is optional/stretch.)

### 3.3 Data aggregation layer
Once a launch is confirmed:
- Fetch full article text for the corroborating sources (use `requests`/
  `httpx` where possible; only reach for a headless browser like Playwright
  if a specific source requires JS rendering to get article text).
- Extract structured facts across sources: product name, launch date,
  headline specs/features, pricing (if announced), notable quotes *about*
  the product from press/analysts (to be paraphrased, not quoted at
  length, in the output).
- Deduplicate overlapping facts across sources.

### 3.4 Stock snapshot layer
- Pull data via `yfinance` (no API key needed) for the launching company's
  ticker.
- Compute: current price, 1-year % change, 52-week high/low, and simple
  trailing-12-month price series (for a chart).
- Optionally: same series for a benchmark (S&P 500 or a sector ETF) for
  visual comparison — presented as parallel context, not a
  causally-linked comparison.

### 3.5 Generation layer
- Use the Claude API (or another LLM) to synthesize a launch summary from
  the aggregated, deduplicated facts — written in the model's own words,
  cross-referencing facts across sources rather than closely following any
  single article's structure or phrasing.
- Output two things per launch:
  1. **Launch summary**: what was announced, key specs/pricing, initial
     reception (paraphrased, attributed to source outlets by name, not
     quoted at length).
  2. **One-pager**: structured combination of the launch summary + the
     stock snapshot section, clearly separated, with a disclaimer line.
- Include a "sources" list (outlet names + links), not verbatim excerpts.

### 3.6 Output / delivery
- Simplest version: generate a Markdown or HTML file per launch, saved
  locally.
- Nicer version (stretch): a small web dashboard (e.g. Flask/FastAPI +
  a simple frontend, or a Streamlit app) listing tracked companies, recent
  launches, and their briefs, with the pending-confirmation queue visible
  for manual approval.

## 4. Suggested tech stack

- **Language**: Python throughout (keeps the whole pipeline in one
  ecosystem, easy to demo).
- **Scheduling**: `APScheduler` or a simple cron job for local/simple
  deployment; Airflow only if you want to demonstrate orchestration tooling
  specifically (likely overkill for v1).
- **News data**: NewsAPI.org / GNews / Bing News Search (pick one) +
  Google News RSS as backup.
- **Article fetching**: `requests` + `BeautifulSoup` for text extraction;
  Playwright only as a fallback for JS-heavy sources.
- **Stock data**: `yfinance`.
- **Storage**: SQLite is enough (tables: `companies`, `trigger_events`,
  `launches`, `briefs`). Postgres only if you want to show that skill
  specifically.
- **Generation**: Claude API (`claude-sonnet-4-6` or similar) for
  synthesis, called with the deduplicated fact set as context and an
  explicit instruction to paraphrase/synthesize rather than closely mirror
  source wording (this also matters for copyright — avoid reproducing
  substantial verbatim text from any single article).
- **Frontend (if built)**: Streamlit is the fastest path to a demoable UI;
  Flask/FastAPI + a lightweight HTML frontend if you want more control for
  a portfolio screenshot/demo.

## 5. Data model sketch

```
companies
  id, name, ticker, keywords (json list)

trigger_events
  id, company_id, source_name, source_tier, url, headline,
  detected_at, matched_query

launches
  id, company_id, product_name, status (pending/confirmed/rejected),
  confirmed_at, corroborating_trigger_event_ids (json list)

briefs
  id, launch_id, summary_text, stock_snapshot (json: price, pct_change,
  52wk_high, 52wk_low), sources (json list), generated_at
```

## 6. Suggested build order (milestones)

1. **Data layer + config**: set up SQLite schema, `companies.yaml` config,
   basic CRUD.
2. **Monitoring layer**: news API integration, polling job, raw trigger
   logging (no corroboration logic yet — just prove you can detect
   candidate events).
3. **Corroboration logic**: source-tier config, matching logic to link
   multiple trigger events into one launch, pending vs. confirmed states.
4. **Stock snapshot layer**: `yfinance` integration, tested independently
   of the news pipeline.
5. **Aggregation + generation layer**: article text fetching, fact
   extraction, Claude API call for synthesis, disclaimer + sources
   section.
6. **Output**: Markdown/HTML file generation per brief.
7. **(Stretch) Dashboard**: Streamlit or Flask view listing companies,
   launches, pending-confirmation queue, and generated briefs.
8. **(Stretch) Event-study add-on**: if you want to push further later,
   add a historical abnormal-return calculation (regress stock against a
   benchmark, measure deviation around past launch dates) — clearly
   labeled as descriptive historical analysis, not prediction. Treat this
   as a v2 feature, not part of the initial build.

## 7. Portfolio framing notes (for the README)

When you write this up for a portfolio, be explicit about:
- Why corroboration/confirmation logic exists (avoiding false positives,
  the same problem as rumor vs. confirmed news in other domains).
- Why the stock section is presented as parallel context rather than a
  causal claim, and why that boundary matters (this shows judgment, not
  just implementation skill).
- What you'd add for a "real" production version (rate limiting/backoff
  on APIs, better dedup, human review UI, more source diversity) — showing
  you know the difference between a portfolio build and a production
  system is itself a good signal.

## 8. Architecture (as built)

Sections 1–7 are the pre-build scope. This section records what the code
actually does and why, so `CLAUDE.md` doesn't have to carry it as
always-on context.

**No database.** Everything is flat files committed to the repo:
`config/companies.yaml` (the NASDAQ-100 universe), `data/state.json`
(every trigger event and group status), `data/briefs/*.md` (the published
briefs), and the git-ignored `data/pending_generation/` (staged facts
handed from the mechanical step to the generation step). At this scale a
database buys nothing and costs a deployment dependency; the repo *is* the
store, and `git log` is the audit trail.

**The mechanical/generation split.** `src/run_daily.py` calls no LLM: it
fetches Google News RSS per company (`src/news.py`), drops obvious
non-launch stories (earnings/dividends/personnel — `BLOCKLIST_PATTERN`),
corroborates via `src/state.py` (≥2 distinct sources, or one tier-1 wire
hit), pulls a Yahoo Finance snapshot (`src/stock.py`), and stages each
newly-confirmed launch to `data/pending_generation/<group_key>_<hash>.json`.
Prose generation then happens inside a Claude Code agent turn — there is
deliberately no `anthropic` API key anywhere in the project. Keeping the
scraping, filtering and corroboration deterministic means the parts that
decide *whether something is true* are auditable code, and the LLM is
confined to the one job it's actually needed for: paraphrasing.

**`src/publish_brief.py` is the generation step's only entrypoint.** It
renders the brief in memory, runs the `src/validate_brief.py` gate
(disclaimer present, no forecasting/banned phrases, no 15-word verbatim
overlap with a source), and only then writes the file, records
`brief_path` + `generated_at` in state, and deletes the staging file. Two
reasons it's one command and not four:

- *Correctness.* Validating before the write means a brief that fails the
  gate is never written at all. Rendering first and checking afterwards
  left failing briefs sitting in `data/briefs/`.
- *Cost.* Every tool call an agent makes re-sends the whole conversation to
  the model. The old sequence (Read staging → render → validate → edit
  state → delete staging) was four round-trips per launch, one of which
  pulled the entire ~60KB `state.json` into context to change two fields.
  Generation runs unattended, every day, forever; the per-run token bill is
  a real design constraint. `run_daily.py`'s `=== PENDING GENERATION ===`
  digest exists for the same reason — it hands the agent the headlines it
  needs and none of the opaque redirect URLs it doesn't.

**Corroboration groups are keyed by `(ticker, matched keyword)`**, not by a
resolved distinct product — an accepted MVP limitation (see "Known
limitations" in the README). The same launch described with two different
verbs still lands in two groups.

**Precision is three independent filters, because the launch verbs are
generic corporate verbs.** "announces" in particular matches promotions,
capex, stock splits, settlements and mission results, and an early audit
found that 9 of 11 "confirmed launches" were noise of exactly this kind. So
a headline must survive all three checks in `src/news.py`:

1. `BLOCKLIST_PATTERN` — kills the non-launch story types outright:
   earnings/legal/personnel, plus market-analyst commentary ("AMD Stock
   Price Forecast: ...Launches July 22"), corporate actions ("Announces
   2-for-1 Stock Split"), capex ("announces $5.7 billion capital
   investment"), and operational milestones ("Announces Full Mission
   Success").
2. `_is_launch_subject` — the company must be the thing *doing* the
   launching, which is not the same as being mentioned near the verb.
   "JPMorgan launches notes tied to AMD, NVIDIA and Tesla" and "As AI Search
   Replaces Google..., Cytd.ai Launches..." both name the company early;
   neither is its news. The test is adjacency: the name must sit close in
   front of the verb with no clause break between (a trailing legal suffix
   like ", Inc." doesn't count as one), and must not be hyphen-attached or
   follow "ex-"/"former"/"rival" ("Ex-Tesla Scientist Unveils...").
3. `SOURCE_BLOCKLIST_MARKERS` — drops ticker-commentary outlets (Zacks,
   TipRanks, Stock Titan, GuruFocus...). They republish launch stories in
   trading framing, and since corroboration only needs two distinct sources,
   two of them agreeing was enough to confirm a launch no primary outlet
   ever covered.

These gate *ingest*. Events already written to `state.json` are not
re-filtered, so tightening the rules does not retroactively un-confirm a
group — that took a one-off purge, and would again.

**One commit per run, at the end.** The pipeline pushes `data/state.json`
and `data/briefs` in a single commit *after* generation completes, not
before. Committing the mechanical step separately would race the generation
step and leave the repo in a state where `state.json` claims a confirmed
launch that has no brief.

**`app.py` is a read-only Streamlit view** over `config/companies.yaml`,
`data/state.json` and `data/briefs/*.md`. No API layer, no writes. It lists
only companies whose `brief_path` is populated, not every "confirmed"
group. It's deployed on Streamlit Community Cloud, which auto-redeploys on
push — hence the `app.py` push-approval hook described in `CLAUDE.md`.
