# Self-Service NL Analytics (side project)

A Streamlit app where a plain-English question about NASDAQ-100 product
launches gets translated into a governed **metric query** — not raw SQL —
compiled to guaranteed-correct DuckDB SQL by a **dbt + MetricFlow**
semantic layer, then answered with a table, a chart, and a visible trace
of the spec and compiled SQL behind it.

Full design: [`PROJECT_PLAN.md`](./PROJECT_PLAN.md).

## Status

**Phase 2 — dbt project + models.** On top of the Phase 1 DuckDB star schema
(below), there's now a **dbt-duckdb** project (`analytics/dbt/`) over the same
file: `staging` views clean each raw table, `marts` build the star schema
(`dim_companies`, `fct_launches`, `fct_stock_snapshots`, `br_launch_sources`),
and dbt `unique`/`not_null`/`relationships` tests plus column descriptions
document and guard it. `dbt build` runs green (9 models, 20 tests). The
MetricFlow semantic layer (`dbt-metricflow` is already installed) and the NL
query flow land in Phases 3+.

**Phase 1 — Dataset & DuckDB.** On top of the Phase 0 scaffold (a
provider-agnostic `LLMClient` and a Streamlit smoke-test page), there's a
DuckDB star schema seeded from the live app's **real** output — the
company universe plus every confirmed, briefed launch and its sources and
stock snapshot. No synthetic *rows* (no backfilled history, no feedback);
every row is real. Only the empty *attribute columns* on those real rows are
filled: company `sector`/`industry`/`market_cap_bucket`/`hq_country` from a
curated real-world map (`company_attrs.csv`), `launches.category` synthesized
(sector-correlated), `launches.confidence_score` a heuristic over real signals
(`num_sources` + wire tier), and `stock_snapshots.change_1d` synthesized.

### Dataset

```
python -m analytics.data.generate_data   # build analytics/data/analytics.duckdb (real data only)
python -m analytics.data.run_sanity      # print the Phase 1 sanity-check queries
```

`analytics.duckdb` is gitignored and fully regenerable from the repo — the
generator reads `data/state.json` and `data/briefs/*` read-only and never
writes them. It's deterministic (fixed seed for the two synthesized columns),
so a rebuild is byte-stable. `launches.product_name` stays empty — the real
name lives in the summary prose and isn't extracted yet. See `data/schema.sql`
for which columns are real, curated, derived, or synthesized.

### dbt models

The `dbt/` project transforms the raw tables into a documented, tested star
schema in the **same** DuckDB file. Regenerate the raw data first, then build:

```
python -m analytics.data.generate_data                              # raw tables
dbt build --project-dir analytics/dbt --profiles-dir analytics/dbt  # staging + marts + tests
dbt docs generate --project-dir analytics/dbt --profiles-dir analytics/dbt   # catalog
```

Run dbt from the repo root (the profile's DuckDB `path` is repo-root-relative;
override with `DBT_DUCKDB_PATH` for an absolute path). `staging/stg_*` are
views that clean each raw table; `marts/` are the tables the semantic layer
will sit on — `dim_companies`, `fct_launches`, `fct_stock_snapshots`,
`br_launch_sources` (feedback stays staging-only while empty). Because dbt
writes into the same file the generator rebuilds from scratch, always
regenerate then `dbt build`, not the reverse.

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
