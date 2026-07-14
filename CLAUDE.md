# CLAUDE.md

## Commands

```
pip install -r requirements.txt               # deps (uses the project .venv in local dev)

python -m src.run_daily                       # mechanical pipeline: news -> corroboration -> staging
python -m src.run_daily --tickers AAPL,MSFT   # scope a run to specific tickers (testing)
python -m src.run_daily --show-pending        # reprint the pending-generation digest, no fetching

python -m src.publish_brief data/pending_generation/<id>.json --summary "<prose>"
                                              # render + validate + record + clear staging, in one call

python -m src.build_universe                  # one-off: (re)scrape NASDAQ-100 -> config/companies.yaml
streamlit run app.py                          # local frontend
```

No test suite, linter, or build step. For the full daily procedure use the **daily-run** skill;
for design rationale see `product-launch-tracker-scope.md`.

## Invariants

- **`run_daily.py` calls no LLM.** There is deliberately no `anthropic` key in this project — the
  brief prose is written by a Claude Code agent turn, not a script.
- **`data/pending_generation/` must never be committed.** It's git-ignored: the one place raw
  scraped article text transiently lives, and this repo is public. Never `git add -A`.
- **Only the launch summary is generated text.** The disclaimer, stock snapshot and sources are
  template-rendered in `src/brief_template.py` and stay code-owned.
- **`data/state.json` is ~60KB and grows daily.** Never Read or Edit it to change a few fields —
  `src/state.py` and `src/publish_brief.py` maintain it in-process.

## Push approval gate for app.py

`.git/hooks/pre-push` blocks any push whose diff touches `app.py` unless `APP_PUSH_APPROVED=1` is
set. app.py changes go live immediately via Streamlit Cloud's auto-redeploy, so they need explicit
user review first: show the diff, get sign-off, then push as `APP_PUSH_APPROVED=1 git push`.
Routine pipeline pushes (`data/state.json`, `data/briefs/*.md`) are exempt.
