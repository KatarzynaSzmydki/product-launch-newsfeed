# Plan — issue #13: add a "how this works" explainer to the page

- **Issue:** [#13](https://github.com/KatarzynaSzmydki/product-launch-newsfeed/issues/13) —
  *not sure how to use this - there's no "how this works" content on the page itself. A one-line
  explainer near the top would help a lot*
- **Classification:** functionality / UX request — adds value.

## Problem

A first-time visitor lands on the dashboard with no on-page explanation of what it is or how to
read it. The README explains the two-source-corroboration model and the "not a forecast" stance,
but nobody arriving at the live app has read the README. The date-navigator + company-list layout
isn't self-evident, so the app reads as unexplained until you click around.

## Proposed approach

Add a short one-line explainer directly under the existing title/caption in the left column of
`app.py` (right after the `st.caption(f"NASDAQ · tracked in the news · last update ...")` line,
before the search box). Keep it to a single sentence in a muted `st.caption`, e.g. framing it as:
tracks NASDAQ-100 companies for product launches, only shows a launch once independent sources
corroborate it, pick a date then a company to read the brief.

Constraints to respect (`product-launch-tracker-scope.md` §2 non-goals): the wording must not
imply forecasting or that launches move the stock — purely descriptive of what the page shows and
how to navigate it. This is copy/layout only; no pipeline, state, or data-model change.

Optional (only if it stays visually clean): pair the one-liner with a small `st.expander`
("How this works") holding the 4-step corroboration→brief flow from the README, collapsed by
default so it doesn't crowd the nav. Decide during implementation; the one-line caption is the
core ask and is sufficient on its own.

## Affected files

- `app.py` — insert the explainer caption in the left column, just below the title/caption block
  (near lines 245–248, before the search `st.text_input`). No other file changes required.

## Notes

`app.py` changes go via a feature branch + PR the user merges (see `CLAUDE.md` branching policy;
a pre-push hook also blocks `app.py` on `master`). The PR body should close this issue with
`Fixes #13`.
