# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```
pip install -r requirements.txt          # deps (uses the project .venv in local dev)

python -m src.build_universe             # one-off: (re)scrape NASDAQ-100 -> config/companies.yaml
python -m src.run_daily                  # mechanical pipeline: news -> corroboration -> staging
python -m src.run_daily --tickers AAPL,MSFT   # scope a run to specific tickers (testing)

python -m src.render_brief data/pending_generation/<id>.json \
    --summary "<generated prose>" --output data/briefs/<date>_<ticker>_<keyword>.md
python -m src.validate_brief data/briefs/<file>.md --staging data/pending_generation/<id>.json

streamlit run app.py                     # local frontend
```

There is no test suite, linter, or build step configured in this repo.

## Architecture

No database — everything is flat files, committed to the repo (see `README.md` for the full breakdown of `config/companies.yaml`, `data/state.json`, `data/briefs/*.md`, `data/pending_generation/`). Read the README before making pipeline changes; the essentials:

- **`run_daily.py` is mechanical only and calls no LLM.** It fetches Google News RSS per company (`src/news.py`), filters obvious non-launch stories (earnings/dividends/personnel — see `BLOCKLIST_PATTERN`), corroborates via `src/state.py` (≥2 distinct sources, or one tier-1 wire hit), pulls a stock snapshot (`src/stock.py`), and stages newly-confirmed launches to `data/pending_generation/<group_key>_<hash>.json`.
- **Generation happens inside a Claude Code agent turn, not a script.** There is deliberately no `anthropic` API key anywhere in this project — the routine's own conversational turn reads each staged JSON, writes the paraphrased launch-summary prose, then calls `render_brief.py` (assembles the full brief — disclaimer and stock-snapshot section are template-rendered in code, only the summary is generated text) followed by `validate_brief.py` as a hard gate (disclaimer present, no banned/forecasting phrases, no verbatim-copied source snippet). A brief that fails validation is not written; its staging file is left for the next run. On success, delete the staging file and record `generated_at` via `state.mark_generated`.
- **`data/pending_generation/` is git-ignored and must never be committed** — it's the one place raw scraped article text transiently exists, and this repo is public.
- Corroboration groups are keyed by `(ticker, matched keyword)`, not a resolved distinct product — an accepted MVP limitation (see README's "Known limitations").
- A pipeline run ends with a single `git add data/state.json data/briefs && commit && push` *after* generation completes, not before — avoids a two-commit race between the mechanical and generation steps.
- `app.py` is a read-only Streamlit view over `config/companies.yaml`, `data/state.json`, and `data/briefs/*.md` — no API layer, no writes. It only lists companies whose `brief_path` is already populated (not every "confirmed" group). Deployed on Streamlit Community Cloud, which redeploys automatically on push to this repo's public GitHub remote.

## Push approval gate for app.py

`.git/hooks/pre-push` blocks any push whose diff touches `app.py` (the deployed frontend) unless `APP_PUSH_APPROVED=1` is set. This is intentional: app.py changes go live immediately via Streamlit Cloud's auto-redeploy, so they need explicit user review first — show the diff, get sign-off, then push as `APP_PUSH_APPROVED=1 git push`. Routine pipeline pushes (`data/state.json`, `data/briefs/*.md` from the standard `run_daily.py` + generation flow) are exempt and need no approval.
