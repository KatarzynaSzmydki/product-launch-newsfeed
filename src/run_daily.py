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

Deliberately does not touch git. The daily-run skill
(.claude/skills/daily-run/) owns the surrounding sequence: run this, then
generate + publish each staged brief, then a single commit + push at the
end -- see "Architecture (as built)" in product-launch-tracker-scope.md for
why two separate commits per run were rejected. data/pending_generation/ is
git-ignored and this script never assumes otherwise.

The run ends by printing a compact digest of everything awaiting
generation; the agent turn reads that instead of the staging JSON files.
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


def _staging_prefix(group_key):
    return group_key.replace("::", "_")


def has_pending_staging_file(group_key):
    """True if a group already has an unpublished staging file.

    Staging filenames encode the group key (see stage_for_generation), so
    this is a glob rather than a state.json lookup -- a group stays
    "confirmed, no brief_path" for as long as its staging file is
    unpublished, so re-running the mechanical step before generation
    catches up would otherwise stage the same group again on every run.
    """
    if not STAGING_DIR.exists():
        return False
    return any(STAGING_DIR.glob(f"{_staging_prefix(group_key)}_*.json"))


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
    staging_path = STAGING_DIR / f"{_staging_prefix(group_key)}_{uuid.uuid4().hex[:8]}.json"
    staging_path.write_text(json.dumps(staged, indent=2), encoding="utf-8")
    return staging_path


def print_pending_digest():
    """Print exactly what the generation step needs to write its prose, and
    nothing else. The agent reads this instead of Read-ing each staging JSON:
    the raw files are dominated by opaque Google News redirect URLs and a
    stock snapshot that publish_brief injects itself, none of which the
    summary prose ever refers to.
    """
    staging_files = sorted(STAGING_DIR.glob("*.json")) if STAGING_DIR.exists() else []

    print(f"\n=== PENDING GENERATION ({len(staging_files)}) ===")
    if not staging_files:
        print("Nothing to generate.")
        return

    for i, path in enumerate(staging_files, start=1):
        staged = json.loads(path.read_text(encoding="utf-8"))
        rel = path.relative_to(REPO_ROOT).as_posix()
        print(f"[{i}] {rel}")
        print(
            f"    {staged['ticker']} - {staged['company_name']} "
            f"- keyword: {staged['keyword']}"
        )
        for article in staged["articles"]:
            source = article["source_name"] or "unknown source"
            print(f"    - {source}: {article['title']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tickers",
        help="Comma-separated tickers to restrict this run to (for scoped testing)",
    )
    parser.add_argument(
        "--show-pending",
        action="store_true",
        help="Reprint the pending-generation digest from existing staging files and exit, "
        "without running the pipeline (e.g. after a brief failed validation)",
    )
    args = parser.parse_args()

    if args.show_pending:
        print_pending_digest()
        return

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
        if has_pending_staging_file(group_key):
            print(f"SKIP (already staged, awaiting generation): {group_key}")
            continue
        staging_path = stage_for_generation(
            group_key, group, ticker_to_name, today, snapshots.get(group["ticker"])
        )
        if staging_path:
            staged_count += 1

    print(
        f"Done. {len(companies)} companies checked, {len(touched_groups)} groups had new "
        f"activity, {staged_count} staged for generation."
    )

    print_pending_digest()


if __name__ == "__main__":
    main()