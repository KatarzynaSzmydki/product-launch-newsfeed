"""Phase 0 smoke test: proves the LLM client can reach a real provider end to end.

Later phases replace this page with the real flow — question box -> validated
metric-query spec -> MetricFlow-compiled SQL -> result table -> chart. See
`product-launch-tracker-scope.md`-adjacent project plan, section 5, for the
target architecture.
"""

import os

import streamlit as st
from dotenv import load_dotenv

from analytics.llm.client import get_default_client

load_dotenv()  # local dev: reads analytics/.env

# Streamlit secrets (deploy) take priority when both are present; .env covers local dev.
if "GEMINI_API_KEY" not in os.environ or not os.environ["GEMINI_API_KEY"]:
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY")
    except FileNotFoundError:
        # st.secrets raises FileNotFoundError (not None) when no secrets.toml exists at all,
        # e.g. before the deploy secret is configured.
        secret_key = None
    if secret_key:
        os.environ["GEMINI_API_KEY"] = secret_key

st.set_page_config(page_title="NL Analytics — Phase 0", page_icon="📊")
st.title("Self-Service NL Analytics — Phase 0 smoke test")
st.caption(
    "This page only proves the LLM client works end to end. The real "
    "NL-to-metric-query flow lands in later phases."
)

prompt = st.text_input("Test prompt", value="Say hello in exactly five words.")

if st.button("Call the LLM"):
    try:
        client = get_default_client()
    except RuntimeError as exc:
        st.error(str(exc))
    else:
        with st.spinner("Calling Gemini..."):
            try:
                reply = client.generate(prompt)
            except Exception as exc:  # surfaces API errors (bad key, quota, ...) directly
                st.error(f"LLM call failed: {exc}")
            else:
                st.success("Got a response:")
                st.write(reply)
