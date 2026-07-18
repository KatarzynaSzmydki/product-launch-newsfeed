"""Phase 7 (partial) — the NL-analytics trust loop, end to end in Streamlit.

A plain-English question becomes a governed metric-query spec (LLM, from the
catalog), which MetricFlow compiles to guaranteed-correct DuckDB SQL, which runs
and comes back as a table + a simple chart. Every answer shows its work: the
spec, the model's assumptions, and the compiled SQL.

Deliberately partial: the semantic cache and 👍/👎 logging (Phase 5) and the
richer Plotly chart synthesis (Phase 6) are not wired yet — this page skips
straight to a working demo of Phase 4's engine over the Phase 3 semantic layer.

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
from analytics.nl2metric.catalog import is_time_dimension

load_dotenv()  # local dev: reads analytics/.env

# Streamlit secrets (deploy) take priority when both are present; .env covers local dev.
if "GEMINI_API_KEY" not in os.environ or not os.environ["GEMINI_API_KEY"]:
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY")
    except FileNotFoundError:
        secret_key = None
    if secret_key:
        os.environ["GEMINI_API_KEY"] = secret_key

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
    metric_set = set(spec.metrics)
    metric_cols = [c for c in result.columns if c in metric_set]
    dim_cols = [c for c in result.columns if c not in metric_cols]
    df = _numeric_frame(result.rows, metric_cols)

    # Single scalar (one metric, no breakdown) reads best as a big number.
    if not dim_cols and len(df) == 1 and len(metric_cols) == 1:
        st.metric(metric_cols[0], df[metric_cols[0]].iloc[0])
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        _render_chart(df, dim_cols, metric_cols)

    st.caption(
        f"⚡ {result.latency_ms:,.0f} ms · {result.row_count} row(s) · "
        "cache + 👍/👎 land in Phase 5"
    )


def _render_chart(df: pd.DataFrame, dim_cols: list[str], metric_cols: list[str]) -> None:
    """A minimal rule-based chart: time → line, one category → bar, else nothing.

    The full shape-aware synthesis (scatter, metric cards, multi-series) is Phase 6.
    """
    if len(dim_cols) != 1 or not metric_cols:
        return
    dim = dim_cols[0]
    chart_df = df.set_index(dim)[metric_cols]
    if is_time_dimension(dim):
        st.line_chart(chart_df)
    else:
        st.bar_chart(chart_df)


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

if st.button("Answer", type="primary") and question.strip():
    _answer(question.strip(), show_sql=show_sql)
