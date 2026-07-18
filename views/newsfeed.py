"""Streamlit frontend -- reads flat files off disk, no API layer of its own.

data/state.json and data/briefs/*.md are updated by the daily routine and
pushed to this public repo; Streamlit Community Cloud redeploys on every
push. streamlit-autorefresh re-runs this script periodically so an open
tab picks up new data / recovers cleanly after a redeploy.

Layout follows wireframe.png: a left pane with a paginated date-card
navigator (day + confirmed-company count) above a company list, and a
right detail pane for the selected company's headline/stock/summary.

Rendered as a page of the st.navigation router in app.py, not run directly.
"""
import json
import re
from datetime import date as date_cls, datetime, timezone
from pathlib import Path

import requests
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPANIES_PATH = REPO_ROOT / "config" / "companies.yaml"
STATE_PATH = REPO_ROOT / "data" / "state.json"
FEEDBACK_REPO = "KatarzynaSzmydki/product-launch-newsfeed"

AUTOREFRESH_INTERVAL_MS = 5 * 60 * 1000
DATE_WINDOW_SIZE = 4
FEEDBACK_MIN_LENGTH = 5
FEEDBACK_MAX_LENGTH = 2000

STOCK_FIELD_PATTERNS = {
    "current_price": r"\|\s*Current price\s*\|\s*\$([\d.,]+)\s*\|",
    "pct_change_1y": r"\|\s*1-year change\s*\|\s*(-?[\d.,]+)%\s*\|",
    "week52_high": r"\|\s*52-week high\s*\|\s*\$([\d.,]+)\s*\|",
    "week52_low": r"\|\s*52-week low\s*\|\s*\$([\d.,]+)\s*\|",
}
SUMMARY_PATTERN = re.compile(r"## Launch Summary\s*\n\n(.*?)\n\n##", re.S)

st_autorefresh(interval=AUTOREFRESH_INTERVAL_MS, key="autorefresh")

# Selection state (date card / company row) is expressed via type="primary",
# but Streamlit's default primary color is red -- override it to grey so a
# "selected" row doesn't read as an alert/error state.
st.markdown(
    """
    <style>
    button[kind="primary"],
    button[kind="primary"]:hover,
    button[kind="primary"]:focus,
    button[kind="primary"]:active,
    button[kind="primary"]:focus:not(:active) {
        background-color: #4b5563 !important;
        border-color: #4b5563 !important;
        color: white !important;
        box-shadow: none !important;
        outline: none !important;
    }
    button[kind="secondary"]:hover,
    button[kind="secondary"]:focus,
    button[kind="secondary"]:active,
    button[kind="secondary"]:focus:not(:active) {
        border-color: #4b5563 !important;
        color: #4b5563 !important;
        box-shadow: none !important;
        outline: none !important;
    }
    /* Streamlit's built-in top loading bar defaults to a red-to-yellow
       gradient and flashes on every rerun (i.e. every button click) --
       neutralize it so a selection click never reads as red. */
    div[data-testid="stDecoration"] {
        background: #4b5563 !important;
        background-image: none !important;
    }
    /* Shrink button padding and inter-row spacing so the company table
       fits more rows per page. */
    div[data-testid="stButton"] button {
        padding-top: 0.25rem !important;
        padding-bottom: 0.25rem !important;
        min-height: 0 !important;
        overflow: hidden !important;
    }
    /* A long company name would otherwise wrap to a second line and grow
       that row's button taller than its neighbors. Force one line with an
       ellipsis instead; the full name is still available via the button's
       hover tooltip (see `help=` in app.py). */
    div[data-testid="stButton"] button p {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    div[data-testid="stVerticalBlock"] {
        gap: 0.35rem !important;
    }
    /* Streamlit reserves several rems above the page for its toolbar even
       when the toolbar itself is hidden -- reclaim that space so the title
       sits near the top instead of floating mid-viewport. */
    div.block-container {
        padding-top: 0.75rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_companies():
    if not COMPANIES_PATH.exists():
        return []
    with COMPANIES_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_state():
    if not STATE_PATH.exists():
        return {"groups": {}}
    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def last_updated(state):
    dates = []
    for group in state.get("groups", {}).values():
        dates.extend(e["detected_at"] for e in group.get("trigger_events", []) if e.get("detected_at"))
        if group.get("generated_at"):
            dates.append(group["generated_at"])
    return max(dates) if dates else None


def format_date_label(iso_date):
    d = date_cls.fromisoformat(iso_date)
    return f"{d.strftime('%a').upper()} {d.day} {d.strftime('%b')}"


def parse_brief(brief_path):
    """Pulls the launch-summary prose and stock stats back out of a brief's
    template-rendered markdown, so the detail panel can show them as
    distinct UI elements instead of one markdown blob. Relies on
    brief_template.py's exact formatting.
    """
    text = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""

    summary_match = SUMMARY_PATTERN.search(text)
    summary = summary_match.group(1).strip() if summary_match else text

    stock = None
    if "Stock data unavailable" not in text:
        values = {}
        for field, pattern in STOCK_FIELD_PATTERNS.items():
            match = re.search(pattern, text)
            if match:
                values[field] = float(match.group(1).replace(",", ""))
        if len(values) == len(STOCK_FIELD_PATTERNS):
            stock = values

    return {"summary": summary, "stock": stock}


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


companies = load_companies()
state = load_state()
groups = state.get("groups", {})
ticker_to_name = {c["ticker"]: c["name"] for c in companies}

confirmed_groups = [
    g for g in groups.values() if g["status"] == "confirmed" and g.get("brief_path")
]

# Group by confirmed date, then by ticker -- a company can have more than one
# confirmed group on the same date (e.g. under both "announces" and
# "unveils"); those stack together under one company entry.
groups_by_date = {}
for group in confirmed_groups:
    d = group.get("confirmed_at")
    if not d:
        continue
    groups_by_date.setdefault(d, {}).setdefault(group["ticker"], []).append(group)

available_dates = sorted(groups_by_date.keys())

# Ticker -> every distinct date it has a confirmed launch on, newest first --
# powers both the global search (jump to a company regardless of date) and
# the per-company timeline tab.
groups_by_ticker = {}
for d, companies_for_d in groups_by_date.items():
    for t in companies_for_d:
        groups_by_ticker.setdefault(t, set()).add(d)
groups_by_ticker = {t: sorted(dates, reverse=True) for t, dates in groups_by_ticker.items()}

if "date_window_start" not in st.session_state:
    st.session_state.date_window_start = max(0, len(available_dates) - DATE_WINDOW_SIZE)
if "selected_date" not in st.session_state and available_dates:
    st.session_state.selected_date = available_dates[-1]

left, right = st.columns([1.3, 1], gap="large")

with left:
    st.title("Product Launches")
    st.caption(f"NASDAQ · tracked in the news · last update {last_updated(state) or 'never'}")

    st.markdown(
        "Each NASDAQ-100 company is checked daily for product-launch news. A launch is "
        "listed here only once **independent sources corroborate it**, which filters out "
        "routine press releases and financial coverage. Every confirmed launch gets a "
        "short plain-language brief and a current stock snapshot.\n\n"
        "**To use it:** pick a date, then a company, to read its brief."
    )

    st.write("")
    st.write("")

    if not available_dates:
        st.info("No confirmed launches with a generated brief yet.")
    else:
        search_query = st.text_input(
            "Search company or ticker",
            key="search_query",
            placeholder="Search company or ticker…",
            label_visibility="collapsed",
        )

        st.write("")

        if search_query.strip():
            q = search_query.strip().lower()
            matches = sorted(
                (
                    (d, t)
                    for t, dates in groups_by_ticker.items()
                    if q in t.lower() or q in ticker_to_name.get(t, "").lower()
                    for d in dates
                ),
                key=lambda match: match[0],
                reverse=True,
            )

            st.write("")
            if not matches:
                st.info(f'No launches match "{search_query}".')
            else:
                with st.container(border=True):
                    for d, t in matches:
                        label = f"{ticker_to_name.get(t, t)}  ·  {t}  —  {format_date_label(d)}"
                        if st.button(label, key=f"search_row_{d}_{t}", use_container_width=True):
                            st.session_state.selected_date = d
                            st.session_state.selected_ticker = t
                            st.rerun()
        else:
            start = st.session_state.date_window_start
            window_dates = available_dates[start : start + DATE_WINDOW_SIZE]

            nav_cols = st.columns([0.5] + [1] * len(window_dates) + [0.5])
            with nav_cols[0]:
                if st.button("◀", disabled=(start <= 0), key="date_prev"):
                    st.session_state.date_window_start = max(0, start - DATE_WINDOW_SIZE)
                    st.rerun()
            for i, d in enumerate(window_dates):
                with nav_cols[i + 1]:
                    selected = d == st.session_state.get("selected_date")
                    if st.button(
                        format_date_label(d),
                        key=f"datecard_{d}",
                        use_container_width=True,
                        type="primary" if selected else "secondary",
                    ):
                        st.session_state.selected_date = d
                        st.session_state.pop("selected_ticker", None)
                        st.rerun()
            with nav_cols[-1]:
                if st.button(
                    "▶", disabled=(start + DATE_WINDOW_SIZE >= len(available_dates)), key="date_next"
                ):
                    st.session_state.date_window_start = min(
                        max(0, len(available_dates) - DATE_WINDOW_SIZE), start + DATE_WINDOW_SIZE
                    )
                    st.rerun()

            selected_date = st.session_state.selected_date
            companies_for_date = groups_by_date.get(selected_date, {})
            tickers = sorted(companies_for_date, key=lambda t: ticker_to_name.get(t, t))

            st.write("")
            st.write("")

            # Each row is a single button (name + ticker in one label) rather than
            # a button next to separate table cells/grid lines -- a button's own
            # box never lines up pixel-for-pixel with independent column/divider
            # grid lines, which read as misalignment. One shape per row sidesteps
            # that entirely. Native st.dataframe row-selection was tried first and
            # dropped: its click target isn't the visible row, so clicks silently
            # did nothing (see project history).
            with st.container(border=True):
                for t in tickers:
                    selected = t == st.session_state.get("selected_ticker")
                    label = f"{ticker_to_name.get(t, t)}  ·  {t}"
                    if st.button(
                        label,
                        key=f"company_row_{selected_date}_{t}",
                        use_container_width=True,
                        type="primary" if selected else "secondary",
                        help=ticker_to_name.get(t, t),
                    ):
                        st.session_state.selected_ticker = t
                        st.rerun()

with right:
    selected_ticker = st.session_state.get("selected_ticker")
    selected_date = st.session_state.get("selected_date")
    ticker_groups = (
        groups_by_date.get(selected_date, {}).get(selected_ticker) if selected_ticker else None
    )

    if not ticker_groups:
        st.info("Select a company on the left to view its brief.")
    else:
        # Streamlit's fixed top toolbar overlaps the first ~60px of the page;
        # without this spacer the close button's top edge renders underneath it.
        st.write("")
        st.write("")
        st.write("")
        st.write("")
        header_col, close_col = st.columns([5, 1])
        with header_col:
            st.subheader(f"{selected_ticker} · {ticker_to_name.get(selected_ticker, selected_ticker)}")
        with close_col:
            if st.button("✕", key="close_detail"):
                st.session_state.pop("selected_ticker", None)
                st.rerun()

        ticker_dates = groups_by_ticker.get(selected_ticker, [])
        launch_tab, timeline_tab = st.tabs(["This launch", f"Timeline ({len(ticker_dates)})"])

        with launch_tab:
            # A company can have more than one confirmed group on the same date
            # (e.g. one corroborated under "introduces", another under "launches")
            # -- that split is an artifact of the corroboration keyword, not
            # something a reader cares about, so all groups for this company/date
            # merge into one view: one stock snapshot, every summary, one combined
            # headline list.
            parsed_groups = []
            for group in ticker_groups:
                brief_path = REPO_ROOT / group["brief_path"]
                if not brief_path.exists():
                    st.error(f"Brief file missing on disk: {group['brief_path']}")
                    continue
                parsed_groups.append((group, brief_path, parse_brief(brief_path)))

            st.markdown("**Stock snapshot**")
            stock = next((p["stock"] for _, _, p in parsed_groups if p["stock"]), None)
            if stock:
                pct = stock["pct_change_1y"]
                arrow = "▲" if pct >= 0 else "▼"
                color = "#1a7f37" if pct >= 0 else "#cf222e"
                st.caption("1-year change")
                st.markdown(
                    f"<span style='font-size:2rem;font-weight:600;color:{color}'>"
                    f"{arrow} {pct:+.1f}%</span>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"Current price \\${stock['current_price']:.2f} · "
                    f"52-week range \\${stock['week52_low']:.2f}–\\${stock['week52_high']:.2f}"
                )

                # Older briefs (published before this sidecar existed) simply
                # have no .prices.json -- render nothing rather than an error.
                price_series = None
                for _, brief_path, _ in parsed_groups:
                    sidecar_path = brief_path.with_suffix(".prices.json")
                    if sidecar_path.exists():
                        try:
                            price_series = json.loads(sidecar_path.read_text(encoding="utf-8"))["series"]
                        except (json.JSONDecodeError, KeyError):
                            price_series = None
                        if price_series:
                            break
                if price_series:
                    st.line_chart(price_series, height=100)
            else:
                st.caption("Stock data unavailable for this run.")

            st.markdown("**Summary**")
            for _, _, parsed in parsed_groups:
                st.write(parsed["summary"])

            # A story can corroborate more than one keyword-group, so dedup by
            # URL rather than listing it once per group.
            seen_urls = set()
            headline_events = []
            for group, _, _ in parsed_groups:
                for e in group.get("trigger_events", []):
                    if e.get("url") and e["url"] not in seen_urls:
                        seen_urls.add(e["url"])
                        headline_events.append(e)

            if headline_events:
                st.markdown("**Headlines & Sources**")
                for e in headline_events:
                    source = e.get("source_name") or "unknown source"
                    st.markdown(f"- [{e['title']}]({e['url']}) ({source})")

        with timeline_tab:
            for d in sorted(ticker_dates, reverse=True):
                day_groups = groups_by_date.get(d, {}).get(selected_ticker, [])
                if not day_groups:
                    continue
                preview_path = REPO_ROOT / day_groups[0]["brief_path"]
                preview = parse_brief(preview_path)["summary"] if preview_path.exists() else ""
                preview = (preview[:90] + "…") if len(preview) > 90 else preview
                is_current = d == selected_date

                date_col, title_col = st.columns([1, 3])
                with date_col:
                    if st.button(
                        format_date_label(d),
                        key=f"timeline_{selected_ticker}_{d}",
                        use_container_width=True,
                        type="primary" if is_current else "secondary",
                    ):
                        st.session_state.selected_date = d
                        st.rerun()
                with title_col:
                    st.write(preview or "(no summary)")

st.divider()
st.caption(
    "**Not investment advice.** This page shows historical/current stock data only — "
    "no forecasts, and the stock section is not a claim that price moves were caused by "
    "the launch."
)

st.write("")
st.write("")
with st.container(border=True):
    with st.expander("Feedback / questions", expanded=False):
        if st.session_state.get("feedback_submitted"):
            st.success("Thanks — your feedback was submitted.")
        else:
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
