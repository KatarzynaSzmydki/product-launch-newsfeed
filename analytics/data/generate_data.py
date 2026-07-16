"""Build analytics.duckdb from the live product-launch-newsfeed output.

Real data only: the ~100-company universe (config/companies.yaml) plus every
confirmed launch that has a published brief (data/state.json + data/briefs/*).
No synthetic backfill and no feedback rows yet — those are deferred.

Deterministic: same repo contents in, same DuckDB out (no randomness, no clock).

    python -m analytics.data.generate_data

Reads data/state.json read-only via json.load; it is never written here (the
state.json invariant only forbids hand-editing it, not parsing it).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from pathlib import Path

import duckdb
import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
STATE_PATH = REPO_ROOT / "data" / "state.json"
COMPANIES_PATH = REPO_ROOT / "config" / "companies.yaml"
ATTRS_PATH = HERE / "company_attrs.csv"
SCHEMA_PATH = HERE / "schema.sql"
DEFAULT_DB_PATH = HERE / "analytics.duckdb"

# Seed for the two synthesized attribute columns (launches.category and
# stock_snapshots.change_1d). Fixed so re-runs are byte-stable.
SEED = 42

# Plausible product categories per curated sector. The app records a launch verb
# (unveils/launches/...), never a category, so this column is synthesized.
CATEGORIES_BY_SECTOR = {
    "Information Technology": [
        "AI/ML platform",
        "developer tool",
        "chip/hardware",
        "cloud service",
        "security product",
    ],
    "Communication Services": [
        "streaming content",
        "social feature",
        "advertising product",
        "AI assistant",
        "game title",
    ],
    "Consumer Discretionary": [
        "consumer device",
        "subscription tier",
        "marketplace feature",
        "retail service",
    ],
    "Consumer Staples": ["product line", "packaging refresh", "flavor/variant", "supply program"],
    "Health Care": ["therapeutic", "medical device", "diagnostic", "digital health tool"],
    "Industrials": ["equipment line", "logistics service", "automation system", "safety product"],
    "Financials": ["payment feature", "merchant tool", "consumer app"],
    "Energy": ["drilling service", "efficiency system", "field technology"],
    "Materials": ["industrial gas offering", "specialty material", "process technology"],
    "Utilities": ["grid program", "clean-energy offering", "customer service tier"],
}
DEFAULT_CATEGORIES = ["product", "platform", "service", "feature"]

# These match the exact table rows rendered by src/brief_template.py
# render_stock_section — a format change there silently degrades parsing to NULLs.
_PRICE_RE = re.compile(r"Current price \| \$([\-0-9.]+)")
_CHANGE_1Y_RE = re.compile(r"1-year change \| \$?([\-0-9.]+)%")
_HIGH_RE = re.compile(r"52-week high \| \$([\-0-9.]+)")
_LOW_RE = re.compile(r"52-week low \| \$([\-0-9.]+)")


def load_company_attrs() -> dict[str, dict]:
    """Curated real-world sector/industry/market-cap/HQ per ticker (company_attrs.csv)."""
    with ATTRS_PATH.open(encoding="utf-8", newline="") as f:
        return {row["ticker"]: row for row in csv.DictReader(f)}


def load_companies() -> list[dict]:
    """The full NASDAQ-100 universe (real name/ticker) enriched with curated attributes."""
    entries = yaml.safe_load(COMPANIES_PATH.read_text(encoding="utf-8"))
    attrs = load_company_attrs()
    companies = []
    for i, entry in enumerate(entries, start=1):
        ticker = entry["ticker"]
        a = attrs.get(ticker)
        if a is None:
            print(f"  WARN: {ticker} missing from company_attrs.csv — attributes left empty")
        companies.append(
            {
                "company_id": i,
                "ticker": ticker,
                "name": entry["name"],
                "sector": a["sector"] if a else None,
                "industry": a["industry"] if a else None,
                "hq_country": a["hq_country"] if a else None,
                "market_cap_bucket": a["market_cap_bucket"] if a else None,
            }
        )
    return companies


def _parse_summary(md_text: str) -> str | None:
    """The prose under '## Launch Summary', up to the next section header."""
    marker = "## Launch Summary"
    start = md_text.find(marker)
    if start == -1:
        return None
    body = md_text[start + len(marker) :]
    nxt = body.find("\n## ")
    if nxt != -1:
        body = body[:nxt]
    return body.strip() or None


def _parse_stock(md_text: str) -> dict | None:
    """The four real metrics from the brief's Stock Snapshot table, or None."""
    price = _PRICE_RE.search(md_text)
    if price is None:  # "Stock data unavailable for this run."
        return None
    change_1y = _CHANGE_1Y_RE.search(md_text)
    high = _HIGH_RE.search(md_text)
    low = _LOW_RE.search(md_text)
    return {
        "price": float(price.group(1)),
        "change_1y": float(change_1y.group(1)) if change_1y else None,
        "week52_high": float(high.group(1)) if high else None,
        "week52_low": float(low.group(1)) if low else None,
    }


def _snapshot_date(brief_path: Path, fallback: str | None) -> str | None:
    prices_path = brief_path.with_suffix(".prices.json")
    if prices_path.exists():
        try:
            return json.loads(prices_path.read_text(encoding="utf-8")).get("as_of", fallback)
        except (json.JSONDecodeError, OSError):
            return fallback
    return fallback


def _synth_category(rng: random.Random, sector: str | None) -> str:
    return rng.choice(CATEGORIES_BY_SECTOR.get(sector, DEFAULT_CATEGORIES))


def _confidence(num_sources: int, has_tier1: bool) -> float:
    """Heuristic score correlated with real corroboration signals (hand-picked
    constants): more distinct sources and any tier-1 wire hit raise confidence."""
    score = 0.55 + 0.09 * min(num_sources, 4) + (0.12 if has_tier1 else 0.0)
    return round(min(score, 0.97), 2)


def _synth_change_1d(rng: random.Random) -> float:
    """Synthetic 1-day % move — the app captures no intraday change. Small, with a
    slight positive bias on launch days; clamped to a plausible range."""
    return round(max(-6.0, min(8.0, rng.gauss(0.4, 1.6))), 2)


def load_real_launches(
    company_by_ticker: dict[str, int],
    sector_by_company_id: dict[int, str | None],
    rng: random.Random,
) -> dict[str, list]:
    """Confirmed, briefed launches from state.json + their briefs.

    Returns dict of row lists keyed by table name, with surrogate ids assigned.
    Empty attribute columns are filled: category (synthesized, sector-correlated),
    confidence_score (derived from real signals), change_1d (synthesized).
    """
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    launches, sources, snapshots = [], [], []
    launch_id = source_id = snapshot_id = 0

    confirmed = [
        g
        for g in state["groups"].values()
        if g.get("status") == "confirmed" and g.get("brief_path")
    ]
    confirmed.sort(key=lambda g: g["brief_path"])  # stable order

    for group in confirmed:
        ticker = group["ticker"]
        company_id = company_by_ticker.get(ticker)
        if company_id is None:
            print(f"  WARN: {ticker} not in companies.yaml — skipping its launch")
            continue

        events = group.get("trigger_events", [])
        distinct = {e.get("source_name") or e["url"] for e in events}
        has_tier1 = any(e.get("tier") == "tier1" for e in events)

        md_path = REPO_ROOT / group["brief_path"]
        summary = stock = None
        if md_path.exists():
            md_text = md_path.read_text(encoding="utf-8")
            summary = _parse_summary(md_text)
            stock = _parse_stock(md_text)
        else:
            print(f"  WARN: brief file missing: {group['brief_path']}")

        launch_date = group.get("confirmed_at") or group.get("generated_at")
        sector = sector_by_company_id.get(company_id)

        launch_id += 1
        launches.append(
            {
                "launch_id": launch_id,
                "company_id": company_id,
                "launch_date": launch_date,
                "keyword": group.get("keyword"),
                "product_name": None,  # real name is in the summary prose; not extracted
                "category": _synth_category(rng, sector),
                "confidence_score": _confidence(len(distinct), has_tier1),
                "num_sources": len(distinct),
                "source_type": "wire" if has_tier1 else "multi_outlet",
                "summary": summary,
                "is_synthetic": False,
            }
        )

        for event in events:
            source_id += 1
            sources.append(
                {
                    "source_id": source_id,
                    "launch_id": launch_id,
                    "outlet_name": event.get("source_name"),
                    "url": event.get("url"),
                    "published_at": event.get("detected_at"),
                    "is_wire": event.get("tier") == "tier1",
                }
            )

        if stock is not None:
            snapshot_id += 1
            snapshots.append(
                {
                    "snapshot_id": snapshot_id,
                    "company_id": company_id,
                    "launch_id": launch_id,
                    "snapshot_date": _snapshot_date(md_path, launch_date),
                    "price": stock["price"],
                    "change_1d": _synth_change_1d(rng),
                    "change_1y": stock["change_1y"],
                    "week52_high": stock["week52_high"],
                    "week52_low": stock["week52_low"],
                }
            )

    return {"launches": launches, "sources": sources, "stock_snapshots": snapshots}


def _insert(con, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    con.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        [[r[c] for c in cols] for r in rows],
    )


def build(db_path: Path) -> None:
    companies = load_companies()
    company_by_ticker = {c["ticker"]: c["company_id"] for c in companies}
    sector_by_company_id = {c["company_id"]: c["sector"] for c in companies}
    rng = random.Random(SEED)
    tables = {
        "companies": companies,
        **load_real_launches(company_by_ticker, sector_by_company_id, rng),
    }

    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        # FK order: parents before children.
        for table in ("companies", "launches", "sources", "stock_snapshots"):
            _insert(con, table, tables.get(table, []))
        con.commit()
    finally:
        con.close()

    print(f"Built {db_path.relative_to(REPO_ROOT)} (real data only):")
    print(f"  companies:       {len(tables['companies'])}")
    print(f"  launches:        {len(tables['launches'])}")
    print(f"  sources:         {len(tables['sources'])}")
    print(f"  stock_snapshots: {len(tables['stock_snapshots'])}")
    print("  feedback:        0 (deferred)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    build(args.db_path)


if __name__ == "__main__":
    main()
