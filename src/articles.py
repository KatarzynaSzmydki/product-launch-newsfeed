"""Best-effort full-article-text fetch, reduced to a short snippet.

Only a short snippet is ever returned -- never the full body -- so raw
scraped article text never risks ending up staged (and possibly
committed) in the public repo.
"""
import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT = 15
MAX_SNIPPET_CHARS = 600


def fetch_snippet(url, max_chars=MAX_SNIPPET_CHARS):
    """Returns a short plain-text snippet from the article, or None on
    any failure (blocked, JS-rendered, non-HTML, network error, ...).
    Callers should fall back to the RSS title/snippet in that case.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "product-launch-newsfeed/0.1"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = " ".join(p for p in paragraphs if p)
    except Exception:
        return None

    text = " ".join(text.split())
    return text[:max_chars] or None
