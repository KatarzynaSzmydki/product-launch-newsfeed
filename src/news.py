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
    r"executive compensation|appoints .*? as|names .*? as|succession plan|"
    # Personnel, restated. "announces" is a generic corporate verb, so it
    # drags in every promotion and reshuffle: "Copart Announces Promotion Of
    # Jane Pocock To President" was confirming as a product launch.
    r"promotion of|promotes .*? to|leadership chang\w*|management chang\w*|"
    r"realignment|new (ceo|cfo|coo|president|chair\w*)|"
    # Corporate actions and capex. Also not products: "Intel announces $5.7
    # billion capital investment in Ireland", "Monster Beverage Announces
    # 2-for-1 Stock Split", "Walmart announces price cuts".
    r"stock split|\d+-for-\d+|reverse split|"
    r"capital investment|investment in|invests? \$|"
    r"new (plant|factory|campus|facility)|"
    # "probe" is deliberately qualified: an unqualified \bprobe\b would
    # block a genuine space-probe launch, which is a real product for some
    # of the universe (RKLB).
    r"settle\w*|fine of|penalt\w*|antitrust|(regulatory|federal|doj|sec|ftc) probe|"
    r"price cuts?|price (increase|hike)s?|announces? discounts?|"
    # Operational milestones, not launches: "Rocket Lab Announces Full
    # Mission Success on VICTUS HAZE".
    r"mission success|mission complete|"
    # Market/analyst commentary. A launch verb inside a price-forecast
    # headline ("AMD Stock Price Forecast: Zen 6 Venice Launches July 22;
    # Is $584 Next?") is a real launch being discussed as a trading thesis,
    # not a launch announcement -- and it drags exactly the forecasting
    # language the brief validator bans into the source material.
    r"stock (price|forecast|prediction|split|analysis|to buy|to watch)|"
    r"price (forecast|prediction)|share price|target price|valuation|"
    r"analyst\w*|outperform|underperform|overweight|underweight|"
    r"bull(ish)? case|bear(ish)? case|market cap|shares of|best stocks?|"
    # Structured products: a bank "launches notes tied to" a basket of
    # tickers. The named companies aren't launching anything.
    r"structured notes?|callable notes?|notes tied to|etf|index fund"
    r")\b",
    re.IGNORECASE,
)

TIER1_SOURCE_MARKERS = ("reuters", "associated press", "ap news", "bloomberg")

# Outlets that exist to comment on tickers, not to report product news.
# They republish launch stories wrapped in trading framing, and because
# corroboration only needs 2 distinct sources, two of these agreeing was
# enough to confirm a "launch" that no primary outlet ever covered.
SOURCE_BLOCKLIST_MARKERS = (
    "stock titan",
    "stocktitan",
    "tradingkey",
    "zacks",
    "simply wall st",
    "insider monkey",
    "marketbeat",
    "tipranks",
    "motley fool",
    "24/7 wall st",
    "invezz",
    "stocktwits",
    "seeking alpha",
    "barchart",
    "investing.com",
    "gurufocus",
    "benzinga",
)

# The company has to be the thing *doing* the launching, not merely named
# near it. Two headlines that both mention the company early but aren't its
# news:
#
#   "JPMorgan (JPM) launches auto callable notes tied to AMD, NVIDIA..."
#   "As AI Search Replaces Google for Millions of Consumers, Cytd.ai
#    Launches to Help Businesses Stay Visible"
#
# Both name the company within the first 60 characters, so a positional
# window admits them. What actually distinguishes a subject is adjacency to
# the verb with no clause break in between: a real launch headline reads
# "<Company> [modifier] <verb>". So require the name to sit close in front
# of the verb, with nothing but a short, unbroken run of text between them.
SUBJECT_VERB_GAP_CHARS = 30
CLAUSE_BREAK_PATTERN = re.compile(r"[,;:–—]")

# ...but a legal suffix trailing the company name is not a clause break, even
# though it carries a comma: "Advanced Micro Devices, Inc. unveils Zen 6" is
# AMD launching. Consume it before testing the gap.
GAP_LEGAL_SUFFIX_PATTERN = re.compile(
    r"^,?\s*(Inc\.?|Corporation|Corp\.?|Company|Co\.?|plc|N\.V\.|Holdings?|Ltd\.?|LLC|Group|"
    r"Technologies|Systems|Solutions|Platforms|Pharmaceuticals)\.?\s*",
    re.IGNORECASE,
)

# ...but preceding the verb still isn't enough on its own. "Ex-Tesla
# Scientist Unveils Plans For European Humanoid Robot" puts Tesla before the
# verb, yet the subject is a person who used to work there. Same for a
# rival/supplier/partner named attributively. A mention disqualifies itself
# as the subject if it's hyphen-attached or follows one of these.
NOT_THE_SUBJECT_PATTERN = re.compile(
    r"(ex|former|onetime|one-time|late|rival|competitor|supplier|partner|"
    r"backed|owned|founded|led)[\s\-]+$",
    re.IGNORECASE,
)

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


def _is_launch_subject(title, company, keyword_index):
    prefix = title[:keyword_index]
    for variant in _name_variants(company):
        for match in re.finditer(rf"\b{re.escape(variant)}\b", prefix, re.IGNORECASE):
            preceding = prefix[: match.start()]
            if preceding.endswith("-") or NOT_THE_SUBJECT_PATTERN.search(preceding):
                continue
            gap = GAP_LEGAL_SUFFIX_PATTERN.sub("", prefix[match.end() :])
            if len(gap) > SUBJECT_VERB_GAP_CHARS or CLAUSE_BREAK_PATTERN.search(gap):
                continue
            return True
    return False


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


def fetch_entries(query, label=""):
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
    # Deliberately terse: this is one line per company, and a Google News
    # outage fires it for all ~100 of them straight into the routine agent's
    # context. The full query adds ~150 chars each and diagnoses nothing.
    print(
        f"WARNING: RSS fetch failed after {RETRY_ATTEMPTS} attempts "
        f"for {label or 'query'}: {type(last_error).__name__}"
    )
    return []


def is_blocked(title):
    return bool(BLOCKLIST_PATTERN.search(title))


def is_blocked_source(source_name):
    if not source_name:
        return False
    lowered = source_name.lower()
    return any(marker in lowered for marker in SOURCE_BLOCKLIST_MARKERS)


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
    """The *earliest* launch verb in the title, with its position.

    Position matters -- _is_launch_subject needs to know what precedes the
    verb -- so this returns the first verb by occurrence in the headline,
    not the first by LAUNCH_KEYWORDS order.
    """
    best = None
    for kw in LAUNCH_KEYWORDS:
        match = re.search(rf"\b{kw}\b", title, re.IGNORECASE)
        if match and (best is None or match.start() < best[1]):
            best = (kw, match.start())
    return best


def trigger_events_for_company(company, today):
    """Fetch and filter new candidate trigger events for one company.

    `today` is an ISO date string (YYYY-MM-DD), passed in by the caller so
    this module has no direct clock dependency.
    """
    events = []
    query = build_query(company["name"], company.get("aliases"), today)
    for entry in fetch_entries(query, label=company["ticker"]):
        title = entry.get("title", "")
        link = entry.get("link")
        if not title or not link or is_blocked(title):
            continue
        matched = _matched_keyword(title)
        if matched is None:
            continue
        keyword, keyword_index = matched
        if not _is_launch_subject(title, company, keyword_index):
            continue
        source_name = extract_source_name(entry)
        if is_blocked_source(source_name):
            continue
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
