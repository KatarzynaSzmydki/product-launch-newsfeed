"""One-off scrape of NASDAQ-100 constituents into config/companies.yaml.

Not part of the daily routine — index composition changes only a few
times a year. Re-run manually after a reconstitution.

Source: stockanalysis.com's Nasdaq-100 stocks list. Wikipedia's
"Nasdaq-100" article no longer carries a components table (it was split
off at some point and only a non-ticker category page remains), so this
uses a site that maintains a plain Symbol/Company Name table specifically
for this purpose.
"""
import re
import sys
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

SOURCE_URL = "https://stockanalysis.com/list/nasdaq-100-stocks/"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "config" / "companies.yaml"

# Companies whose press coverage commonly uses a different name than the
# index/legal entity name. These are also some of the highest
# launch-volume names, so missing them would hurt recall the most.
ALIASES = {
    "Alphabet Inc.": ["Google"],
    "Meta Platforms, Inc.": ["Meta", "Facebook"],
}

# Nasdaq-100 lists dual share classes for a handful of companies (e.g.
# Alphabet's GOOGL/GOOG). Keep only the preferred ticker per company so we
# don't double-count or double-brief the same firm.
PREFERRED_TICKER_OVERRIDES = {
    "Alphabet Inc.": "GOOGL",
}


def _normalize_name(name):
    # Strips trailing "(Class A)"-style annotations so dual-class rows
    # collapse to the same company key.
    return re.sub(r"\s*\(.*?\)\s*$", "", name).strip()


def fetch_constituents():
    resp = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; product-launch-newsfeed/0.1)"},
        timeout=30,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for table in soup.find_all("table"):
        header_cells = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not header_cells:
            continue
        if any("symbol" in h for h in header_cells) and any(
            "company" in h for h in header_cells
        ):
            return _parse_table(table, header_cells)

    raise RuntimeError(
        f"Could not find the Nasdaq-100 constituents table at {SOURCE_URL} "
        "-- its page structure may have changed."
    )


def _parse_table(table, header_cells):
    ticker_idx = next(i for i, h in enumerate(header_cells) if "symbol" in h)
    company_idx = next(i for i, h in enumerate(header_cells) if "company" in h)

    companies = {}
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) <= max(ticker_idx, company_idx):
            continue
        raw_name = cells[company_idx].get_text(strip=True)
        ticker = cells[ticker_idx].get_text(strip=True)
        if not raw_name or not ticker:
            continue
        ticker = re.sub(r"\s+", "", ticker).upper()
        name = _normalize_name(raw_name)

        if name in companies:
            preferred = PREFERRED_TICKER_OVERRIDES.get(name)
            if preferred and ticker == preferred:
                companies[name] = ticker
            continue
        companies[name] = ticker

    return companies


def build_companies_yaml():
    constituents = fetch_constituents()

    entries = []
    for name, ticker in sorted(constituents.items()):
        entry = {"name": name, "ticker": ticker}
        if name in ALIASES:
            entry["aliases"] = ALIASES[name]
        entries.append(entry)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(entries, f, sort_keys=False, allow_unicode=True)

    return entries


if __name__ == "__main__":
    written = build_companies_yaml()
    print(f"Wrote {len(written)} companies to {OUTPUT_PATH}")
    if not (90 <= len(written) <= 110):
        print(
            f"WARNING: expected roughly 100 constituents, got {len(written)} — "
            "check that Wikipedia's table structure hasn't changed.",
            file=sys.stderr,
        )
