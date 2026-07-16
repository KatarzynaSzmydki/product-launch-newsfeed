# Self-Service NL Analytics (side project)

A Streamlit app where a plain-English question about NASDAQ-100 product
launches gets translated into a governed **metric query** — not raw SQL —
compiled to guaranteed-correct DuckDB SQL by a **dbt + MetricFlow**
semantic layer, then answered with a table, a chart, and a visible trace
of the spec and compiled SQL behind it.

Full design: [`PROJECT_PLAN.md`](./PROJECT_PLAN.md).

## Status

**Phase 0 — Foundations.** Module scaffold, a provider-agnostic
`LLMClient`, and a Streamlit smoke-test page that proves the LLM call
works end to end. Nothing here answers real questions yet — that starts
with the dataset (Phase 1) and the dbt/MetricFlow semantic layer
(Phases 2–3).

## Setup

```
pip install -r analytics/requirements-dev.txt   # runtime + ruff/black/pytest
cp analytics/.env.example analytics/.env         # then fill in GEMINI_API_KEY
pre-commit install                               # optional, scoped to analytics/
streamlit run analytics/app.py
```

Get a free Gemini key (no card required) at
https://aistudio.google.com/apikey. Locally it's read from
`analytics/.env`; when deployed it should instead go in Streamlit's
`secrets.toml` under the same `GEMINI_API_KEY` name (never commit either
file).

## Why a separate LLM provider from the main app

The main `product-launch-newsfeed` app deliberately has no LLM API key —
its brief prose is written by a Claude Code agent turn, not a script (see
the root `CLAUDE.md`). This side project is different: it's a standalone
app that needs to call an LLM API at request time to translate a question
into a metric-query spec, so it carries its own key and its own
`LLMClient` abstraction (`analytics/llm/client.py`), independent of the
main app's pipeline.

## Design principle

The LLM never writes SQL and never touches the database. It only emits a
small JSON object chosen from a predefined catalog of metrics and
dimensions; deterministic Python validates it, and MetricFlow compiles it
into SQL. See `PROJECT_PLAN.md` section 3 for why this beats text-to-SQL
for governed self-service.
