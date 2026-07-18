"""Streamlit entrypoint -- routes between the newsfeed and the NL-analytics page.

Streamlit Community Cloud runs this file. It holds no page logic of its own:
each page's body lives in its own script and is executed by st.navigation.

set_page_config lives here and only here. Under st.navigation the entrypoint
re-runs before every page run, so a second call inside a page script would
raise -- page-level title/icon go through st.Page instead.
"""
import streamlit as st

from views.feedback import render_sidebar

st.set_page_config(page_title="Product Launch Tracker", layout="wide")

page = st.navigation(
    [
        st.Page(
            "views/newsfeed.py",
            title="Product Launches",
            icon=":material/newspaper:",
            default=True,
        ),
        st.Page(
            "analytics/app.py",
            title="Ask the data",
            icon=":material/insights:",
        ),
    ]
)

# Before run(), so the form sits under the nav links rather than below whatever
# the page happens to render into the sidebar.
render_sidebar()

page.run()
