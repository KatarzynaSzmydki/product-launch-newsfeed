"""Stock snapshot layer -- current price, 1y % change, 52-week high/low.

Calls Yahoo Finance's public chart JSON endpoint directly via `requests`
rather than through the `yfinance` package: yfinance's cookie/crumb
handshake has become unreliable as Yahoo has tightened bot-blocking on its
API, while the underlying chart endpoint itself is still a plain public
JSON GET with no auth required -- and conveniently already returns
`fiftyTwoWeekHigh`/`fiftyTwoWeekLow` pre-computed.

No forecasting of any kind: only historical/current data, per the
project's explicit non-goals.
"""
import time

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
REQUEST_TIMEOUT = 15
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 3


def get_snapshot(ticker):
    """Returns a dict of historical/current facts, or None if Yahoo
    didn't return usable data after retries. Callers should skip
    generating a brief this run rather than publish one with a blank or
    broken stock section.
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        snapshot = _try_fetch(ticker)
        if snapshot is not None:
            return snapshot
        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    return None


def _try_fetch(ticker):
    try:
        resp = requests.get(
            CHART_URL.format(ticker=ticker),
            params={"range": "1y", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; product-launch-newsfeed/0.1)"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None

    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        return None
    result = results[0]

    meta = result.get("meta", {})
    quotes = (result.get("indicators") or {}).get("quote") or [{}]
    closes = [c for c in (quotes[0].get("close") or []) if c is not None]
    if not closes:
        return None

    current_price = meta.get("regularMarketPrice") or closes[-1]
    year_ago_price = closes[0]
    week52_high = meta.get("fiftyTwoWeekHigh")
    week52_low = meta.get("fiftyTwoWeekLow")

    if not current_price or not year_ago_price or week52_high is None or week52_low is None:
        return None

    pct_change_1y = (current_price - year_ago_price) / year_ago_price * 100

    return {
        "ticker": ticker,
        "current_price": round(float(current_price), 2),
        "pct_change_1y": round(float(pct_change_1y), 2),
        "week52_high": round(float(week52_high), 2),
        "week52_low": round(float(week52_low), 2),
        "price_series": _downsample(closes),
    }


def _downsample(closes, stride=5):
    """Every `stride`th close plus the final one, so a sparkline covers the
    full 1y window in ~50 points instead of ~250 -- fine for a small chart,
    a fraction of the JSON size of the full daily series.
    """
    series = [round(float(c), 2) for c in closes[::stride]]
    last = round(float(closes[-1]), 2)
    if series[-1] != last:
        series.append(last)
    return series
