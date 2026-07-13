"""Google News RSS monitoring layer.

Google News RSS `<link>` values are opaque redirects through
news.google.com, not the publisher's own domain -- extracting a "domain"
from them would make every article look like the same source. Publisher
identity instead comes from the RSS `<source>` element, which feedparser
exposes as entry.source.title / entry.source.href.
"""
import re
import time
from datetime import date, timedelta
from urllib.parse import quote

import feedparser
import requests

RSS_BASE = "https://news.google.com/rss/search"

LAUNCH_KEYWORDS = ["unveils", "launches", "announces", "reveals", "introduces"]

# Rejects routine corporate-finance/legal/personnel news that the generic
# launch verbs above would otherwise match constantly for large-cap names
# (earnings, dividends, buybacks, class-action law-firm spam, executive
# departures...). This is what keeps "confirmed" meaningful -- without it,
# a wire-service dividend story (or a law firm's "shareholders have an
# opportunity" press release) would auto-confirm as a "launch."
BLOCKLIST_PATTERN = re.compile(
    r"\b("
    r"dividend|earnings|financial results|fiscal (year|quarter)|guidance|buyback|"
    r"repurchase|quarterly results|q[1-4]\s*(20\d{2})?|revenue|eps of|downgrad\w*|upgrad\w*|"
    r"price target|layoffs?|job cuts?|"
    r"class action|investor alert|shareholder rights|securities fraud|law firm|"
    r"law offices?|lawsuit|sued for|urges investors|"
    r"insider trading|form 4|13d|13g|"
    r"steps down|stepping down|departure of|resign\w*|retirement of|executive chang\w*|"
    r"executive compensation|appoints .*? as|names .*? as|succession plan"
    r")\b",
    re.IGNORECASE,
)

TIER1_SOURCE_MARKERS = ("reuters", "associated press", "ap news", "bloomberg")

# A headline mentioning the company only in passing (e.g. a third party's
# press release that happens to name them as a partner/landlord/supplier)
# shouldn't count as that company's own news. Real self-reporting headlines
# put the company name/ticker up front ("Apple unveils...", "AMD Unveils
# New Chip..."); require a name/alias/ticker hit within the first stretch
# of the title as a cheap proxy for "this is about them," not about them.
EARLY_MENTION_CHARS = 60

LEGAL_SUFFIX_PATTERN = re.compile(
    r",?\s*(Inc\.?|Corporation|Corp\.?|Company|Co\.?|plc|N\.V\.|Holdings?|Ltd\.?|LLC|Group|"
    r"Technologies|Systems|Solutions|Platforms|Pharmaceuticals)\.?\s*$",
    re.IGNORECASE,
)

REQUEST_TIMEOUT = 15
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2

# Cheap noise cap: keep only the first few qualifying hits per company per
# run rather than every RSS result. Corroboration only needs 2 distinct
# sources (or 1 tier-1 hit), so a handful is plenty and keeps the daily
# run fast even at 100-company scale.
MAX_EVENTS_PER_COMPANY = 3


def _strip_legal_suffix(name):
    prev = None
    while prev != name:
        prev = name
        name = LEGAL_SUFFIX_PATTERN.sub("", name).strip()
    return name


def _name_variants(company):
    name = company["name"]
    short = _strip_legal_suffix(name)
    variants = {name, short, company["ticker"]}
    if short:
        variants.add(short.split()[0])
    variants.update(company.get("aliases") or [])
    return {v for v in variants if v and len(v) > 1}


def _mentions_company_early(title, company):
    prefix = title[:EARLY_MENTION_CHARS]
    return any(
        re.search(rf"\b{re.escape(variant)}\b", prefix, re.IGNORECASE)
        for variant in _name_variants(company)
    )


def build_query(name, aliases, today):
    names = [name] + list(aliases or [])
    name_clause = " OR ".join(f'"{n}"' for n in names)
    verb_clause = " OR ".join(LAUNCH_KEYWORDS)
    # Google News RSS's after:/before: operators are day-granularity, not
    # hour-granularity -- a same-day-only window would clip stories near
    # the run's UTC boundary. A day on either side of `today` approximates
    # a rolling last-24h window without losing those edge-of-day hits;
    # dedup-by-URL in state.py absorbs the resulting day-to-day overlap.
    today_date = date.fromisoformat(today)
    after = (today_date - timedelta(days=1)).isoformat()
    before = (today_date + timedelta(days=1)).isoformat()
    return f"({name_clause}) ({verb_clause}) after:{after} before:{before}"


def fetch_entries(query):
    url = f"{RSS_BASE}?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "product-launch-newsfeed/0.1"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return feedparser.parse(resp.content).entries
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    print(
        f"WARNING: RSS fetch failed after {RETRY_ATTEMPTS} attempts "
        f"for query={query!r}: {last_error}"
    )
    return []


def is_blocked(title):
    return bool(BLOCKLIST_PATTERN.search(title))


def classify_tier(source_name):
    if not source_name:
        return "other"
    lowered = source_name.lower()
    return "tier1" if any(marker in lowered for marker in TIER1_SOURCE_MARKERS) else "other"


def extract_source_name(entry):
    source = entry.get("source")
    if source and source.get("title"):
        return source["title"]
    # Fallback: Google News titles are usually "Headline - Publisher".
    title = entry.get("title", "")
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return None


def _matched_keyword(title):
    lowered = title.lower()
    for kw in LAUNCH_KEYWORDS:
        if kw in lowered:
            return kw
    return None


def trigger_events_for_company(company, today):
    """Fetch and filter new candidate trigger events for one company.

    `today` is an ISO date string (YYYY-MM-DD), passed in by the caller so
    this module has no direct clock dependency.
    """
    events = []
    query = build_query(company["name"], company.get("aliases"), today)
    for entry in fetch_entries(query):
        title = entry.get("title", "")
        link = entry.get("link")
        if not title or not link or is_blocked(title):
            continue
        keyword = _matched_keyword(title)
        if keyword is None or not _mentions_company_early(title, company):
            continue
        source_name = extract_source_name(entry)
        events.append(
            {
                "url": link,
                "title": title,
                "source_name": source_name,
                "tier": classify_tier(source_name),
                "detected_at": today,
                "keyword": keyword,
            }
        )
        if len(events) >= MAX_EVENTS_PER_COMPANY:
            break
    return events
