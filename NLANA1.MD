# Self-Service NL Analytics Platform — Project Plan

**A portfolio project built on top of `product-launch-newsfeed`**

Version 2.0 · Owner: Katarzyna · Type: side / learning project
Architecture: **text-to-metric-query** on a **dbt + MetricFlow** semantic layer

---

## 1. One-line pitch

A Streamlit app where a non-technical user types a plain-English question about NASDAQ-100 product launches, and the system checks whether it has answered something similar before, translates the question into a governed **metric query** (not raw SQL), lets MetricFlow compile and run guaranteed-correct SQL, and returns an answer plus an auto-chosen chart — while always showing its work.

## 2. Why build it on the existing repo

The `product-launch-newsfeed` app already produces exactly the kind of structured, business-flavoured data that makes NL analytics interesting: entities (companies), events (launches), evidence (sources), and metrics (stock snapshots, confirmation rates). Reusing it means:

- You query a **real domain you understand**, so you can tell when an answer is wrong — the single most important thing for practising NL analytics.
- The two projects compose into one story: *"an app that generates data, and an app that lets anyone interrogate it through a governed semantic layer."*
- You avoid a generic toy dataset (Chinook, Northwind) that every other portfolio uses.

The catch: the live app produces a *small* amount of real data. So Phase 1 includes generating **synthetic-but-realistic** history so queries have something to chew on. Treat the real feed as ground truth and the synthetic rows as backfill.

## 3. The core architectural decision: text-to-metric-query

The naive design is **text-to-SQL** — the LLM writes raw SQL and you try to catch its mistakes. This project deliberately uses the stronger pattern: **text-to-metric-query**.

The LLM never writes SQL. It emits a small structured object chosen from *predefined* metrics and dimensions:

```json
{
  "metrics": ["launch_count"],
  "group_by": ["companies__sector", "metric_time__quarter"],
  "where": ["metric_time >= '2025-01-01'"],
  "order_by": ["-launch_count"],
  "limit": 20
}
```

MetricFlow then compiles this into guaranteed-correct DuckDB SQL — joins, grain, and aggregation all handled by the semantic layer, not the model. The LLM's error surface collapses from "any valid SQL string" to "pick from ~15 metrics and ~10 dimensions." The two most common silent NL→SQL failures — wrong joins and wrong grain — become **structurally impossible**.

Trade-off you're accepting on purpose: the system can only answer questions expressible as `metrics × dimensions × filters`. Truly ad-hoc questions (an odd window function, a one-off join) can't be phrased. For *governed self-service*, that constraint is a feature.

## 4. Scope

**In scope (v1):**
NL question → validated metric-query spec → MetricFlow-compiled SQL → result table → auto-chart → short natural-language answer. Semantic caching of validated questions. An evaluation harness. Auth + deploy + tests + docs.

**Explicitly out of scope (v1):**
Raw free-form SQL, writing back to the DB, multi-turn conversational follow-ups (Phase 10 stretch), dbt Cloud, and any real-money/financial-advice interpretation of results.

**Non-goals:** beating a BI tool on features. The point is to learn the NL-analytics trust loop and dbt end to end.

---

## 5. Target architecture

```
                 ┌─────────────────────────────────────────────┐
                 │                Streamlit UI                  │
                 │  question box · spec/assumptions panel ·     │
                 │  compiled SQL view · table · chart · 👍/👎    │
                 └───────────────┬─────────────────────────────┘
                                 │ NL question
                                 ▼
                    ┌────────────────────────┐   hit
                    │   Semantic cache        ├──────────► return validated spec
                    │  (embed → similarity)   │
                    └────────────┬────────────┘   miss
                                 ▼
   ┌────────────────┐  ┌────────────────────────┐
   │ Metric catalog │─►│  NL→metric-query gen     │  (LLM API; catalog of metrics +
   │ (from dbt      │  └────────────┬────────────┘   dimensions injected into prompt)
   │  MetricFlow:   │               │ candidate spec (JSON)
   │  list_metrics, │               ▼
   │  list_dims)    │  ┌────────────────────────┐
   └────────────────┘  │  Spec validator          │  metric/dimension names exist? ·
                       │                          │  filter columns allowed? · limit set?
                       └────────────┬────────────┘
                                    ▼
                       ┌────────────────────────┐
                       │  MetricFlow             │  compiles spec → DuckDB SQL,
                       │  (dbt-core, local)      │  runs via dbt-duckdb (read-only)
                       └────────────┬────────────┘
                                    ▼
                    ┌────────────────────────────────┐
                    │ Answer + chart synthesis        │  rule-based chart from result
                    │ (+ optional LLM one-liner)      │  shape; LLM summarises numbers
                    └────────────┬────────────────────┘
                                 ▼
                        log to query_log (+ embeddings)
```

**Key principle:** the LLM proposes a *spec*; deterministic code and MetricFlow dispose. The model never writes SQL, never touches the database, and never decides access. Everything between the model and the data is testable Python + a governed semantic layer.

---

## 6. Free vs. paid (important)

- **MetricFlow is open source (Apache 2.0)** and runs on **dbt-core**. You define semantic models + metrics and query them **locally** via the `dbt-metricflow` CLI / Python. This is 100% free and is what this project uses.
- **DuckDB is fully supported** through the `dbt-duckdb` adapter.
- **dbt Cloud Semantic Layer** (the hosted REST/GraphQL/JDBC API with caching, access control, BI integrations) requires a **paid Team/Enterprise plan** — **not used here.** You call MetricFlow locally from Streamlit instead.

Consequence: querying is via the MetricFlow CLI/Python interface (a subprocess or the `mf` Python API), not a slick hosted API. Slightly clunkier to embed, and there's per-query compile overhead — acceptable for a portfolio app.

---

## 7. Tech stack

| Concern | Choice | Why |
|---|---|---|
| UI | Streamlit | You already know it; fine for a portfolio app. |
| Warehouse | DuckDB (file-based) | Zero-setup, fast analytics, works with dbt + MetricFlow. Read-only for queries. |
| Transform + semantic layer | **dbt-core + MetricFlow** (`dbt-metricflow`, `dbt-duckdb`) | The skill you want to learn; owns metric definitions and correct SQL compilation. |
| LLM | **Google Gemini API (free tier)** default; swap to OpenAI/Anthropic behind one `LLMClient` interface | Emits the metric-query spec. Gemini Flash free tier (~1,500 req/day, no card, no expiry) is ample for a demo. |
| Spec validation | Plain Python against the MetricFlow metric/dimension catalog | Deterministic, testable. |
| Embeddings (cache) | **Gemini Embedding (free tier)** — same key as the LLM | ~1,500 req/day free; avoids a second provider and avoids local torch (which won't fit Streamlit Cloud memory). |
| Charts | Plotly (via Streamlit) | Interactive, good defaults. |
| Eval | `pytest` + golden-questions YAML | Regression gate on accuracy. |
| Auth | `streamlit-authenticator` or native Streamlit auth | Gate the demo. |
| CI | GitHub Actions | Lint + tests + `dbt build` + eval on push. |
| Secrets | `.env` + `st.secrets` + dbt `profiles.yml` | Keep keys out of git. |

Hard rule: **everything except the LLM and embedding calls runs offline and is unit-testable.** MetricFlow compilation is deterministic, so you can snapshot-test compiled SQL.

**On the free LLM/embedding tier:**
- One Gemini key serves both the spec-generation LLM and the cache embeddings — simplest possible setup, and the free quotas dwarf a demo app's needs.
- **Fallbacks** if a limit/model gets pulled (free tiers are volatile): **Groq** (fast Llama models, ~1,000 req/day) for spec generation; **OpenRouter** (rotating free models, one key) as a catch-all. All sit behind the same `LLMClient` interface, so switching is a one-module change.
- **Data-use caveat:** free tiers generally reserve the right to train on inputs and have weaker data terms. Fine here — the data is public NASDAQ product-launch info. This is exactly why the free tier would *not* carry over to a real GSK/internal-data scenario; keep that separation explicit in the README.
- Verify current rate limits when you set up — the numbers shift often.

---

## 8. Dataset design

A small star schema in DuckDB. Real rows from the live feed, backfilled with synthetic history. These become dbt **staging + mart models**, and the marts become MetricFlow **semantic models**.

**`companies`** (dim) — `company_id`, `ticker`, `name`, `sector`, `industry`, `hq_country`, `market_cap_bucket`

**`launches`** (fact) — `launch_id`, `company_id`, `launch_date`, `product_name`, `category`, `confidence_score`, `num_sources`, `source_type` (`wire` | `multi_outlet`), `summary`

**`sources`** (bridge) — `source_id`, `launch_id`, `outlet_name`, `url`, `published_at`, `is_wire`

**`stock_snapshots`** (fact) — `snapshot_id`, `company_id`, `launch_id`, `snapshot_date`, `price`, `change_1d`, `change_1y`, `week52_high`, `week52_low`

**`feedback`** (fact) — `feedback_id`, `submitted_at`, `feedback_type`, `status`, `launch_id`

**`query_log`** (operational; powers cache + eval) — `query_id`, `nl_question`, `metric_query_spec`, `compiled_sql`, `result_row_count`, `result_hash`, `latency_ms`, `status`, `user_id`, `created_at`, `question_embedding`, `was_cache_hit`, `user_rating`

Example questions v1 should answer:
- "How many confirmed launches did each sector have last quarter?"
- "Which companies launched the most products this year?"
- "What's the average 1-day stock change on launch days, by sector?"
- "What share of feedback is still open?"

**Synthetic data:** a seeded `generate_data.py` that reads the live app's output and generates plausible historical launches (seasonality around CES/earnings, sector-correlated categories, noisy-but-correlated stock moves), writing everything to the DuckDB file. Document which rows are real vs synthetic.

---

## 9. The dbt / MetricFlow semantic layer

This replaces the hand-written YAML from v1. You define **semantic models** (entities, dimensions, measures) on your dbt marts, then **metrics** on top. Sketch for the launches domain:

```yaml
# models/marts/_launches__semantic.yml
semantic_models:
  - name: launches
    model: ref('fct_launches')
    defaults:
      agg_time_dimension: launch_date
    entities:
      - name: launch
        type: primary
        expr: launch_id
      - name: company
        type: foreign
        expr: company_id
    dimensions:
      - name: launch_date
        type: time
        type_params: { time_granularity: day }
      - name: category
        type: categorical
      - name: source_type
        type: categorical
    measures:
      - name: launch_count
        agg: count_distinct
        expr: launch_id
      - name: avg_confidence
        agg: average
        expr: confidence_score
      - name: multi_sourced_launches
        agg: sum
        expr: "case when num_sources >= 2 then 1 else 0 end"

metrics:
  - name: launch_count
    type: simple
    type_params: { measure: launch_count }
  - name: confirmation_rate
    type: ratio
    type_params:
      numerator: multi_sourced_launches
      denominator: launch_count
```

A `companies` semantic model exposes `sector`, `industry`, `market_cap_bucket` as dimensions joined via the `company` entity — so `group by companies__sector` just works, with MetricFlow guaranteeing the join. Your app reads the available metrics/dimensions from MetricFlow (`mf list metrics`, `mf list dimensions`) to build the catalog it injects into the LLM prompt — so the model can only ever reference things that actually exist.

---

## 10. Phased plan

Each phase ends with something demoable and committed. Roughly one weekend-ish block per phase.

### Phase 0 — Foundations
- New module in the repo (e.g. `analytics/`) or a sibling package.
- Get a free **Gemini API key** (default provider for LLM + embeddings); build a thin, swappable `LLMClient` so Groq/OpenRouter/OpenAI are drop-in later.
- Set up `.env`/secrets, `requirements`, pre-commit (ruff/black), README stub.
- **Done when:** a Streamlit page loads and can call the LLM with a test prompt.

### Phase 1 — Dataset & DuckDB
- Define the raw schema (DDL).
- Write seeded `generate_data.py`: real + synthetic backfill.
- Load into `analytics.duckdb` (gitignored; regenerable).
- **Done when:** you can run 5 hand-written analytical queries returning sensible numbers.

### Phase 2 — dbt project + models *(new: learn dbt here)*
- `dbt init` with the `dbt-duckdb` adapter; `profiles.yml` pointing at the DuckDB file.
- Build **staging** models (clean raw tables) and **mart** models (`fct_launches`, `dim_companies`, `fct_stock_snapshots`, etc.).
- Add dbt **tests** (`not_null`, `unique`, `relationships`) and column descriptions.
- **Done when:** `dbt build` runs green and marts are documented.

### Phase 3 — MetricFlow semantic layer *(the core skill)*
- Add `dbt-metricflow`. Define semantic models (entities/dimensions/measures) and metrics (`launch_count`, `confirmation_rate`, `avg_launch_day_move`, …).
- Verify with the CLI: `mf query --metrics launch_count --group-by companies__sector`.
- Build a **catalog loader** that pulls available metrics + dimensions into a compact prompt block.
- **Done when:** each of the 5 canonical questions is answerable by a hand-written `mf query`.

### Phase 4 — NL→metric-query engine + validation
- Prompt: role, the metric/dimension catalog, few-shot examples, strict JSON output contract (the spec). Capture the model's stated assumptions.
- **Spec validator:** every metric/dimension/filter name exists in the catalog; a limit is present; reject unknown fields. (Far simpler than SQL guardrails — MetricFlow owns join/grain correctness.)
- Executor: pass the validated spec to MetricFlow; run against a **read-only** DuckDB connection with a timeout and row cap.
- **Done when:** unit tests prove invalid/unknown-field specs are rejected and valid ones execute.

### Phase 5 — Semantic cache ("has this been asked before?")
- Embed each incoming question; compare to `query_log` embeddings by cosine similarity.
- **Conservative policy:** only reuse a spec above a high similarity threshold, and only from *validated* past queries. On a near-miss, show the candidate and let the user confirm rather than silently reusing.
- Store new validated question→spec pairs.
- **Done when:** a repeat is a cache hit; a paraphrase is offered as a suggestion; an unrelated question misses. Document why the threshold is high (the correctness trap).

### Phase 6 — Answer & chart synthesis
- Rule-based chart from result shape: metric over time → line; category × metric → bar; single scalar → metric card; two numerics → scatter.
- Optional LLM one-liner grounded strictly in the returned rows (never invents figures).
- **Done when:** the 5 canonical questions render a sensible chart + one-liner.

### Phase 7 — Streamlit UX
- Question box; "Show spec, assumptions & compiled SQL" expander (great teaching surface — you can literally see MetricFlow's SQL); result table; chart; latency + cache-hit badge; 👍/👎 to `query_log`; example-question chips.
- **Done when:** a stranger can use it and always sees *how* the answer was produced.

### Phase 8 — Evaluation harness
- `golden.yaml`: ~30–50 questions, each with an expected spec and/or expected result signature.
- Runner scores generated spec vs golden (exact spec match + result match), outputs an accuracy report.
- Wire into CI as a report first, then a threshold gate.
- **Done when:** `pytest`/make target prints an accuracy % and flags regressions.

### Phase 9 — Auth, deploy, CI/CD, docs
- Gate the app with simple auth; deploy (Streamlit Community Cloud, as your existing app).
- GitHub Actions: lint + unit tests + `dbt build` + eval report on PR.
- Architecture doc, demo GIF/Loom, README "how it works / known limitations."
- **Done when:** it's live, protected, and the repo reads like a finished portfolio piece.

### Phase 10 — Stretch (pick what's fun)
- Multi-turn follow-ups ("now break that down by sector").
- Confidence scoring on the generated spec; auto-flag low-confidence answers.
- "Explain this metric in English" mode.
- Add a dbt **saved query** / metric exposure and surface it.
- Swap DuckDB → Postgres (or MotherDuck) to feel a different MetricFlow engine; add row-level security.

---

## 11. Suggested repo structure

```
analytics/
  app.py                     # Streamlit entry
  llm/client.py              # provider-agnostic LLM + embeddings
  nl2metric/
    prompt.py                # prompt assembly from the metric catalog
    generate.py              # NL -> candidate metric-query spec (JSON)
    catalog.py               # reads mf list metrics/dimensions
  validate/spec.py           # spec validation against the catalog
  exec/runner.py             # MetricFlow execution, read-only, timeouts, caps
  cache/semantic_cache.py    # embed + similarity + store
  viz/chart.py               # rule-based chart selection
  eval/{golden.yaml,run_eval.py}
  tests/
dbt_project/                 # the dbt project (learn dbt here)
  models/
    staging/                 # stg_* cleaned raw
    marts/                   # fct_/dim_ + *_semantic.yml (semantic models + metrics)
  profiles.yml               # dbt-duckdb, points at analytics.duckdb
data/
  schema.sql
  generate_data.py
  analytics.duckdb           # gitignored, regenerable
```

## 12. Risks & how the plan handles them

| Risk | Mitigation |
|---|---|
| Wrong-but-confident answers | Semantic layer guarantees join/grain; spec is validated; UI shows spec + compiled SQL; eval harness measures accuracy. |
| LLM picks nonsense metric/dimension | Spec validator rejects anything not in the MetricFlow catalog (Phase 4). |
| Semantic cache returns subtly wrong spec | High similarity threshold; suggest-don't-auto-reuse; only cache validated specs (Phase 5). |
| Thin real dataset | Seeded synthetic backfill, clearly labelled (Phase 1). |
| Question can't be expressed as metrics×dimensions | Accepted trade-off; app explains it can't answer and suggests nearby metrics. |
| dbt/MetricFlow learning curve | It's a stated goal; Phases 2–3 are scoped as the learning core. |
| Local MetricFlow latency | Cache validated specs; keep DuckDB file warm; acceptable for a demo. |

## 13. Definition of done (v1)

A deployed, auth-gated Streamlit app where a user asks a plain-English question about product launches and reliably gets a correct answer, a chart, and a visible **spec + compiled SQL** trace — powered by a real **dbt + MetricFlow** semantic layer, backed by an eval harness reporting a measured accuracy figure, a spec validator proven by tests, and a README that honestly states what it can and can't do.

## 14. What you'll learn

dbt (staging/marts, tests, docs) and MetricFlow semantic modelling — both highly marketable; the text-to-metric-query pattern and why it beats text-to-SQL for governed analytics; prompt engineering for structured output; embeddings and semantic caching (and its failure modes); LLM output evaluation; and the end-to-end trust loop that separates a demo from a product. That last one, plus dbt, is the transferable skill for the real GSK scenario.

---

## Open questions to resolve at kickoff

1. Which LLM provider/model, and do you have API budget? (Cheap models are fine; note the accuracy trade-off.)
2. How much synthetic history is "enough" — a couple of years of daily launches?
3. Same repo (new `analytics/` + `dbt_project/`) or a sibling repo that reads the first app's DuckDB file?
4. Local DuckDB only, or do you also want to try MotherDuck later (same adapter, cloud-hosted) as a stretch?
