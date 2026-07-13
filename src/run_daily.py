"""Mechanical daily pipeline: news -> corroboration -> stock snapshot
staging -> state.json. Calls no LLM API.

RSS fetches and stock snapshot lookups are I/O-bound and independent per
company/ticker, so both phases run concurrently via a thread pool. State
mutation (state.json) stays single-threaded: each phase fetches
concurrently into a plain dict first, then a serial loop applies the
results to `current_state` -- avoiding any shared-dict race.

Article full-text fetching (src/articles.py) is currently skipped for
speed; the RSS headline is used as the snippet instead. Re-enable by
calling articles.fetch_snippet(event["url"]) in stage_for_generation if
richer source text is wanted later.

Deliberately does not touch git. The scheduled routine is responsible for
the surrounding sequence: a clean checkout before this runs, then (after
this script + the generation step both finish) a single commit + push --
see the "Scheduling" section of the project plan for why two separate
commits per run were rejected. data/pending_generation/ is git-ignored
and this script never assumes otherwise.
"""
import argparse
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import news, stock
from . import state as state_module

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPANIES_PATH = REPO_ROOT / "config" / "companies.yaml"
STATE_PATH = REPO_ROOT / "data" / "state.json"
STAGING_DIR = REPO_ROOT / "data" / "pending_generation"

MAX_WORKERS = 2


def today_utc():
    return datetime.now(timezone.utc).date().isoformat()


def load_companies():
    with COMPANIES_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_ticker_index(companies):
    return {c["ticker"]: c["name"] for c in companies}


def fetch_events_by_ticker(companies, today):
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_ticker = {
            pool.submit(news.trigger_events_for_company, company, today): company["ticker"]
            for company in companies
        }
        for future in as_completed(future_to_ticker):
            results[future_to_ticker[future]] = future.result()
    return results


def fetch_snapshots_by_ticker(tickers):
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_ticker = {pool.submit(stock.get_snapshot, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            results[future_to_ticker[future]] = future.result()
    return results


def stage_for_generation(group_key, group, ticker_to_name, today, snapshot):
    if snapshot is None:
        print(f"SKIP (no usable stock data this run, will retry): {group_key}")
        return None

    ticker = group["ticker"]
    articles_payload = [
        {
            "url": event["url"],
            "source_name": event["source_name"],
            "title": event["title"],
            "snippet": event["title"],
        }
        for event in group["trigger_events"]
    ]

    staged = {
        "group_key": group_key,
        "ticker": ticker,
        "company_name": ticker_to_name.get(ticker, ticker),
        "keyword": group["keyword"],
        "today": today,
        "articles": articles_payload,
        "stock_snapshot": snapshot,
    }

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staging_path = STAGING_DIR / f"{group_key.replace('::', '_')}_{uuid.uuid4().hex[:8]}.json"
    staging_path.write_text(json.dumps(staged, indent=2), encoding="utf-8")
    return staging_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tickers",
        help="Comma-separated tickers to restrict this run to (for scoped testing)",
    )
    args = parser.parse_args()

    today = today_utc()

    companies = load_companies()
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",")}
        companies = [c for c in companies if c["ticker"] in wanted]
    ticker_to_name = build_ticker_index(companies)
    current_state = state_module.load_state(STATE_PATH)

    events_by_ticker = fetch_events_by_ticker(companies, today)

    touched_groups = set()
    for company in companies:
        events = events_by_ticker.get(company["ticker"], [])
        touched = state_module.record_trigger_events(current_state, company["ticker"], events, today)
        touched_groups |= touched

    for group_key in touched_groups:
        state_module.evaluate_confirmation(current_state, group_key, today)

    state_module.apply_staleness(current_state, today)
    state_module.save_state(STATE_PATH, current_state)

    pending = [
        (group_key, group)
        for group_key, group in state_module.groups_needing_generation(current_state)
        # Skip groups outside this run's scope (e.g. a --tickers-scoped test
        # run) -- leave them for a run that covers them.
        if group["ticker"] in ticker_to_name
    ]
    snapshots = fetch_snapshots_by_ticker({group["ticker"] for _, group in pending})

    staged_count = 0
    for group_key, group in pending:
        staging_path = stage_for_generation(
            group_key, group, ticker_to_name, today, snapshots.get(group["ticker"])
        )
        if staging_path:
            staged_count += 1
            print(f"Staged {group_key} -> {staging_path}")

    print(
        f"Done. {len(companies)} companies checked, {len(touched_groups)} groups had new "
        f"activity, {staged_count} staged for generation."
    )


if __name__ == "__main__":
    main()