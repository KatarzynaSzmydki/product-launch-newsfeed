"""Feedback form -- app chrome, rendered in the sidebar on every page.

Opens a GitHub issue labelled `feedback` on the public repo, which the
triage-feedback skill later picks up.
"""
from datetime import datetime, timezone

import requests
import streamlit as st

FEEDBACK_REPO = "KatarzynaSzmydki/product-launch-newsfeed"
FEEDBACK_MIN_LENGTH = 5
FEEDBACK_MAX_LENGTH = 2000


def get_feedback_token():
    # st.secrets.get() raises FileNotFoundError (not None) when no
    # secrets.toml exists at all, e.g. before the deploy secret is configured.
    try:
        return st.secrets.get("github_feedback_token")
    except FileNotFoundError:
        return None


def submit_feedback(text):
    stripped = text.strip()
    if len(stripped) < FEEDBACK_MIN_LENGTH:
        return False, "Please write a bit more before submitting."
    if len(stripped) > FEEDBACK_MAX_LENGTH:
        return False, f"Please keep it under {FEEDBACK_MAX_LENGTH} characters."

    token = get_feedback_token()
    if not token:
        return False, "Feedback is temporarily unavailable."

    title_line = stripped.splitlines()[0]
    title = (title_line[:77] + "...") if len(title_line) > 80 else title_line
    body = (
        f"{stripped}\n\n---\nSubmitted via app feedback form at "
        f"{datetime.now(timezone.utc).isoformat()}"
    )

    try:
        response = requests.post(
            f"https://api.github.com/repos/{FEEDBACK_REPO}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": title, "body": body, "labels": ["feedback"]},
            timeout=10,
        )
    except requests.RequestException:
        return False, "Couldn't submit, try again later."

    if response.status_code != 201:
        return False, "Couldn't submit, try again later."

    return True, None


def render_sidebar():
    with st.sidebar:
        st.divider()
        with st.expander("Feedback / questions", expanded=False):
            if st.session_state.get("feedback_submitted"):
                st.success("Thanks — your feedback was submitted.")
                return

            feedback_text = st.text_area(
                "Comment, question, or suggestion",
                key="feedback_text",
                placeholder="What's on your mind?",
                max_chars=FEEDBACK_MAX_LENGTH,
            )
            token_missing = not get_feedback_token()
            if st.button("Submit", key="feedback_submit", disabled=token_missing):
                ok, message = submit_feedback(feedback_text)
                if ok:
                    st.session_state.feedback_submitted = True
                    st.rerun()
                else:
                    st.error(message)
            if token_missing:
                st.caption("Feedback is temporarily unavailable.")
