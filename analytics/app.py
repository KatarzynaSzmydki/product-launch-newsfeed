"""Phase 7 (partial) — the NL-analytics trust loop, end to end in Streamlit.

A plain-English question becomes a governed metric-query spec (LLM, from the
catalog), which MetricFlow compiles to guaranteed-correct DuckDB SQL, which runs
and comes back as a table plus a shape-appropriate chart. Every answer shows its
work: the spec, the model's assumptions, and the compiled SQL.

Deliberately partial: the semantic cache and 👍/👎 logging (Phase 5) are not
wired yet. Phase 6's chart synthesis is in — the rules live in
analytics/viz/chart.py, pure and tested offline, and this module only renders
what they decide. The phase's optional LLM one-liner was dropped: reading the
chart is the user's job, and a second generated sentence per question buys
little for the free-tier quota it spends.

Rendered as a page of the st.navigation router in app.py, which owns
set_page_config for the whole app.
"""

from __future__ import annotations

import dataclasses
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from analytics.llm.client import get_default_client
from analytics.nl2metric import (
    GenerationError,
    QueryExecutionError,
    generate_spec,
    load_catalog,
    run_spec,
)
from analytics.viz import BAR, LINE, METRIC, SCATTER, choose_chart, split_columns

load_dotenv()  # local dev: reads analytics/.env

# Streamlit secrets (deploy) take priority when both are present; .env covers local dev.
if "GEMINI_API_KEY" not in os.environ or not os.environ["GEMINI_API_KEY"]:
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY")
    except FileNotFoundError:
        secret_key = None
    if secret_key:
        os.environ["GEMINI_API_KEY"] = secret_key

# A soft cap, not a security control: it resets on reload. It exists so a public
# page can't quietly drain the free-tier Gemini quota, while still letting a
# stranger try the demo without a login.
MAX_QUESTIONS_PER_SESSION = 5

EXAMPLE_QUESTIONS = [
    "Which companies launched the most products?",
    "How many launches did each sector have, by quarter?",
    "What's the average launch-day stock move by sector?",
    "What's the confirmation rate by sector?",
    "How many launches happened each month?",
]

@st.cache_resource
def _catalog():
    return load_catalog()


@st.cache_resource
def _client():
    return get_default_client()


def _questions_remaining() -> int:
    # Namespaced key: session_state is shared with the newsfeed page under the router.
    return MAX_QUESTIONS_PER_SESSION - st.session_state.get("analytics_questions_used", 0)


def _prune_empty(value):
    """Recursively drop empty collections and None so the trace stays readable
    (e.g. no ``"grain": null`` on every filter)."""
    if isinstance(value, dict):
        return {k: _prune_empty(v) for k, v in value.items() if v not in ((), [], None, {})}
    if isinstance(value, (list, tuple)):
        return [_prune_empty(v) for v in value]
    return value


def _spec_to_dict(spec) -> dict:
    """A JSON-friendly view of the spec for the trace panel (drops empty fields)."""
    return _prune_empty(dataclasses.asdict(spec))


def _numeric_frame(rows: list[dict], metric_cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in metric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _render_result(spec, result) -> None:
    metric_cols, dim_cols = split_columns(result.columns, spec.metrics)
    df = _numeric_frame(result.rows, metric_cols)
    chart = choose_chart(
        metric_cols,
        dim_cols,
        row_count=len(df),
        distinct_counts={c: int(df[c].nunique()) for c in dim_cols if c in df.columns},
    )

    if chart.kind == METRIC:
        for col, value in zip(st.columns(len(chart.y)), chart.y):
            col.metric(value, df[value].iloc[0])
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        _render_chart(df, chart)

    drawn = f"{chart.kind} chart" if chart else "no chart"
    st.caption(
        f"⚡ {result.latency_ms:,.0f} ms · {result.row_count} row(s) · "
        f"{drawn} — {chart.reason} · cache + 👍/👎 land in Phase 5"
    )


def _render_chart(df: pd.DataFrame, chart) -> None:
    """Draw whatever analytics/viz decided. The rules live there; this only maps
    a ChartSpec onto Streamlit's native charts."""
    if not chart:
        return
    kwargs = {"x": chart.x, "y": list(chart.y)}
    if chart.color:
        kwargs["color"] = chart.color
    if chart.kind == LINE:
        st.line_chart(df, **kwargs)
    elif chart.kind == BAR:
        st.bar_chart(df, **kwargs)
    elif chart.kind == SCATTER:
        st.scatter_chart(df, **kwargs)


def _render_trace(gen, result=None) -> None:
    with st.expander("🔍 Show spec, assumptions & compiled SQL"):
        if gen.spec.assumptions:
            st.markdown(f"**Assumptions:** {gen.spec.assumptions}")
        st.markdown("**Metric-query spec** (what the model chose from the catalog):")
        st.json(_spec_to_dict(gen.spec))
        if result is not None:
            if result.compiled_sql:
                st.markdown("**Compiled SQL** (MetricFlow, not the model):")
                st.code(result.compiled_sql, language="sql")
            st.markdown("**mf query arguments:**")
            st.code(" ".join(result.args), language="text")
        st.markdown("**Raw model reply:**")
        st.code(gen.raw, language="json")


def _answer(question: str, *, show_sql: bool = True) -> None:
    try:
        catalog = _catalog()
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    try:
        client = _client()
    except RuntimeError as exc:
        st.error(str(exc))
        return

    # Charged here and not earlier: the two guards above fail without ever reaching
    # the API, so a missing key or manifest must not cost the visitor a question.
    st.session_state.analytics_questions_used = (
        st.session_state.get("analytics_questions_used", 0) + 1
    )

    try:
        with st.spinner("Translating your question into a metric-query spec…"):
            gen = generate_spec(question, catalog, client)
    except GenerationError as exc:
        st.error(f"Couldn't turn that into a valid metric query: {exc}")
        if exc.errors:
            st.caption("Validation errors: " + "; ".join(exc.errors))
        with st.expander("Raw model reply"):
            st.code(exc.raw or "(empty)", language="json")
        return
    except Exception as exc:  # LLM API errors (bad key, quota, network)
        st.error(f"LLM call failed: {exc}")
        return

    try:
        with st.spinner("Compiling & running via MetricFlow… (first run can take ~30s)"):
            result = run_spec(gen.spec, explain=show_sql)
    except QueryExecutionError as exc:
        st.error(str(exc))
        _render_trace(gen)
        return

    _render_result(gen.spec, result)
    _render_trace(gen, result)


st.title("📊 Ask the product-launch data")
st.caption(
    "Type a question about NASDAQ-100 product launches. It's translated into a "
    "governed **metric query** (never raw SQL), compiled by **dbt + MetricFlow**, "
    "and answered with a table, a chart, and a full trace of how it got there."
)

if "question" not in st.session_state:
    st.session_state.question = EXAMPLE_QUESTIONS[0]

st.write("**Try one:**")
chip_cols = st.columns(len(EXAMPLE_QUESTIONS))
for col, example in zip(chip_cols, EXAMPLE_QUESTIONS):
    if col.button(example, use_container_width=True):
        st.session_state.question = example

question = st.text_input("Your question", key="question")
show_sql = st.checkbox(
    "Show compiled SQL (runs a second MetricFlow pass, adds ~30s)", value=False
)

_capped = _questions_remaining() <= 0

if st.button("Answer", type="primary", disabled=_capped) and question.strip():
    _answer(question.strip(), show_sql=show_sql)

# Read after _answer() so the count reflects the question just asked.
if _questions_remaining() <= 0:
    st.info(
        f"That's all {MAX_QUESTIONS_PER_SESSION} questions for this session. The demo "
        "runs on a free-tier API key, so it's capped to keep it available for "
        "everyone — **reload the page** to start over."
    )
else:
    st.caption(
        f"{_questions_remaining()} of {MAX_QUESTIONS_PER_SESSION} questions left "
        "this session."
    )
