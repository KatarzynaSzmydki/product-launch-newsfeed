"""Flat-file state store for trigger events and launch/group status.

No database -- everything lives in data/state.json. A "group" is
(ticker, matched keyword) rather than a resolved distinct product; see
"Architecture (as built)" in product-launch-tracker-scope.md for why this
simplification was accepted for the MVP (the same launch covered under two
verbs can still land in two groups).

This file is only ever read and written in-process (by run_daily and
publish_brief). It is ~60KB and grows daily -- nothing should be pulling it
into an agent's context to change a couple of fields.
"""
import json
from datetime import date
from pathlib import Path

STALE_AFTER_DAYS = 14


def default_state():
    return {"groups": {}}


def load_state(path):
    path = Path(path)
    if not path.exists():
        return default_state()
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def _group_key(ticker, keyword):
    return f"{ticker}::{keyword}"


def record_trigger_events(state, ticker, events, today):
    """Append new (deduped by URL) trigger events, creating groups as needed.

    Returns the set of group keys that received at least one new event, so
    the caller knows which groups need re-evaluation.
    """
    touched = set()
    for event in events:
        key = _group_key(ticker, event["keyword"])
        group = state["groups"].setdefault(
            key,
            {
                "ticker": ticker,
                "keyword": event["keyword"],
                "status": "pending",
                "first_seen": today,
                "confirmed_at": None,
                "generated_at": None,
                "brief_path": None,
                "trigger_events": [],
            },
        )
        existing_urls = {e["url"] for e in group["trigger_events"]}
        if event["url"] in existing_urls:
            continue
        group["trigger_events"].append(event)
        touched.add(key)
    return touched


def evaluate_confirmation(state, group_key, today):
    """Re-check one group's confirmation rule; mutates state in place.

    Confirmed if trigger events come from >=2 distinct sources, or a
    single tier-1 (wire service) hit -- the tier-1 hit already passed the
    negative-keyword blocklist upstream in news.py, so it isn't a
    dividend/earnings story slipping through as an auto-confirm.
    """
    group = state["groups"][group_key]
    if group["status"] != "pending":
        return

    sources = {e["source_name"] or e["url"] for e in group["trigger_events"]}
    has_tier1_hit = any(e["tier"] == "tier1" for e in group["trigger_events"])

    if len(sources) >= 2 or has_tier1_hit:
        group["status"] = "confirmed"
        group["confirmed_at"] = today


def apply_staleness(state, today, stale_after_days=STALE_AFTER_DAYS):
    """Marks dead pending groups stale so they stop being re-checked.

    A group can still confirm later if new activity arrives before it
    crosses the staleness threshold -- staleness only catches groups with
    no activity at all in the window.
    """
    today_date = date.fromisoformat(today)
    for group in state["groups"].values():
        if group["status"] != "pending":
            continue
        last_detected = max(
            (date.fromisoformat(e["detected_at"]) for e in group["trigger_events"]),
            default=None,
        )
        if last_detected is None:
            continue
        if (today_date - last_detected).days > stale_after_days:
            group["status"] = "stale"


def groups_needing_generation(state):
    return [
        (key, group)
        for key, group in state["groups"].items()
        if group["status"] == "confirmed" and group["brief_path"] is None
    ]


def mark_generated(state, group_key, brief_path, generated_at):
    group = state["groups"][group_key]
    group["brief_path"] = brief_path
    group["generated_at"] = generated_at
