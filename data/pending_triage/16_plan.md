# Plan — issue #16: add summary metrics (launches tracked, companies covered, last 30 days)

- **Issue:** [#16](https://github.com/KatarzynaSzmydki/product-launch-newsfeed/issues/16) —
  *it seems a valuable metric to have total number of launches tracked, companies covered,
  launches in last 30 days*
- **Classification:** functionality / UX request — adds value.

## Problem

The dashboard shows individual launches (date navigator + company list) but gives no at-a-glance
sense of scale — how many launches has the tracker confirmed overall, how many distinct
companies, and how active the last month has been. A first-time or returning visitor has no way
to gauge coverage without manually counting entries.

## Value assessment

Purely descriptive counts derived from data already in `data/state.json` — no forecasting, no
causal claims connecting news to stock moves, no new data source. Fits `product-launch-tracker-scope.md`
§2 non-goals cleanly (nothing here implies a forecast or a stock-move signal). Not a duplicate of
any other open issue. Feasible with the existing mechanical/state architecture: `app.py` already
builds `confirmed_groups` (`app.py:212-214`, filtered to `status == "confirmed"` and has a
`brief_path`) and `groups_by_ticker` (`app.py:231-235`), which are exactly the aggregates needed.

## Proposed approach

Add a small stat row (3 numbers, e.g. via `st.columns` + `st.metric` or plain `st.caption`s) in
the left column of `app.py`, near the existing title/caption block (`app.py:245-246`, before the
explainer paragraph added for #13) — something like:

- **Total launches tracked** — `len(confirmed_groups)`
- **Companies covered** — `len(groups_by_ticker)`
- **Launches in last 30 days** — count of `confirmed_groups` whose `confirmed_at` falls within
  30 days of today (`date_cls.today()`, already imported)

This is template-rendered from existing state, consistent with the "only the launch summary is
generated text" invariant in `CLAUDE.md` — no LLM involved, no new data model or pipeline change.

## Affected files

- `app.py` — insert the stat row in the left column, after the title/caption
  (`app.py:245-254` region), computed from `confirmed_groups` and `groups_by_ticker` which are
  already in scope at that point in the script. No other file changes required.

## Notes

`app.py` changes go via a feature branch + PR the user merges (see `CLAUDE.md` branching policy;
a pre-push hook also blocks `app.py` on `master`). The PR body should close this issue with
`Fixes #16`.
