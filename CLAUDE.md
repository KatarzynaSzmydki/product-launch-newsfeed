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

## Branching policy

Streamlit Cloud auto-redeploys from `master`, so anything that lands there is live immediately.
Where a change goes depends on whether it touches the deployed frontend:

- **`app.py` — never push to `master`.** Branch, push the branch, open a PR, and stop. The user
  reviews and merges it; the PR *is* the approval step, so do not merge it yourself and do not
  ask for a shortcut around it.

  ```
  git switch -c <feature-branch>
  git add app.py && git commit
  git push -u origin <feature-branch>
  gh pr create          # then hand the PR link to the user and stop
  ```

- **Everything else — straight to `master`.** Daily-run output (`data/state.json`,
  `data/briefs/*.md`) and pipeline source (`src/*`, config, docs) need no branch and no PR.

`.git/hooks/pre-push` enforces this: it rejects any push that puts `app.py` on `master`, and has
no override. Pushing `app.py` to a non-master branch is unrestricted. The hook lives in `.git/`
and is therefore local-only — it won't survive a fresh clone, so treat the policy above as the
source of truth, not the hook.
