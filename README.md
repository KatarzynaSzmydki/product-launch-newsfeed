# Product Launch Tracker

Tracks NASDAQ-100 companies for corroborated tech-product-launch news and
generates a one-page brief (launch summary + stock snapshot) per confirmed
launch. Portfolio project — see `product-launch-tracker-scope.md` for the
original scope and non-goals (no forecasting, no causal launch→stock
claims, not investment advice).

## Architecture at a glance

No database — everything is flat files, committed to this repo:

- `config/companies.yaml` — NASDAQ-100 constituents (name, ticker, aliases).
- `data/state.json` — trigger events + launch/group status.
- `data/briefs/*.md` — one generated brief per confirmed launch.
- `data/pending_generation/` — staged facts awaiting a brief. **Git-ignored
  on purpose**: this is the one place raw scraped article text can
  transiently exist, and this repo is public.

The pipeline runs once a day as a **Claude Code scheduled routine** (not
cron/Task Scheduler), in three parts:

1. `python -m src.build_universe` — one-off/occasional, re-run manually
   whenever the NASDAQ-100 index is reconstituted. Not part of the daily run.
2. `python -m src.run_daily` — mechanical steps only (news → corroboration
   → article snippet + stock snapshot → staging). Calls no LLM API.
3. **Generation, inside the routine's own agent turn** — for each file in
   `data/pending_generation/`, Claude reads the staged facts, writes a
   launch-summary paragraph, then:
   - `python -m src.render_brief <staging_file>.json --summary "<generated prose>" --output data/briefs/<date>_<ticker>_<keyword>.md`
     assembles the full brief. The disclaimer and stock-snapshot section
     are template-rendered in code, not left to the LLM — only the prose
     summary is generated text.
   - `python -m src.validate_brief data/briefs/<file>.md --staging <staging_file>.json`
     must pass (exit 0) before the brief is committed. It checks the exact
     disclaimer string is present, that no banned phrase (forecast,
     price target, causal "because of the launch" language, etc.) appears,
     and that no 15+ word span was copied verbatim from a staged source
     snippet. A brief that fails validation is not published; its staging
     file is left for the next run instead.
   - The staging file is deleted once its brief passes validation, and
     `generated_at` is recorded in `state.json`.
4. A **single** `git add data/state.json data/briefs && git commit && git push`
   at the very end of the whole sequence (after generation, not before) —
   deliberately not two separate commits, to avoid a push race between the
   mechanical step and the generation step.

**Why no LLM API key**: generation runs as part of the scheduled routine's
own agent turn, under the existing Claude Pro/Max subscription, not a
metered `anthropic` API call. **Accepted trade-off**: this means the
generation step only runs inside the owner's scheduled routine — cloning
this repo and running the scripts manually will get you through staging,
but won't produce a brief without that routine.

## Frontend

`app.py` is a Streamlit app that reads `config/companies.yaml`,
`data/state.json`, and `data/briefs/*.md` directly off disk — no separate
API layer. It shows a per-company pending/confirmed/stale overview, a feed
of confirmed launches with their rendered briefs, and a pending-corroboration
table. `streamlit-autorefresh` re-polls periodically so an open tab picks up
new data pushed by the routine.

Deploy on **Streamlit Community Cloud**, pointed at this public GitHub repo
— it redeploys automatically on every push. No secrets needed for the
Streamlit deployment; it only ever reads already-generated files.

Local run:

```
pip install -r requirements.txt
streamlit run app.py
```

## Setting up the daily routine

Register a Claude Code scheduled routine (`schedule` skill / `CronCreate`)
pinned to a fixed UTC time, whose job is the full sequence in
"Architecture at a glance": clean checkout → `run_daily.py` → generation
loop over `data/pending_generation/` → single commit + push.

Routine environment needs:
- Repo cloned fresh each firing (or reset to `origin/main`) so it never
  pushes from stale local state.
- `pip install -r requirements.txt`.
- Git identity (`user.name` / `user.email`) configured.
- Push credentials scoped to just this repo (fine-grained PAT with
  `contents:write`, or a deploy key) — kept as a secret, never committed.
  This is the only credential the project needs.

## Known limitations (accepted MVP trade-offs)

- Corroboration groups by `(ticker, matched keyword)`, not by resolved
  distinct product — the same launch covered under two verbs ("unveils"
  vs. "launches") can land in two groups.
- Tier-1 sources are a small fixed wire-service list (AP, Reuters,
  Bloomberg) — a legitimate official launch announcement with no wire
  pickup yet won't auto-confirm on a single hit.
- Best-effort article text fetch: sources that need JS rendering fall back
  to the RSS headline/snippet.
- Generation only runs inside the scheduled routine (see above).
