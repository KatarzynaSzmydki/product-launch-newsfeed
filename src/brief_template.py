"""Code-owned pieces of every brief -- kept out of the LLM's hands so the
disclaimer and stock section are always present and correctly worded.
Only the launch-summary prose is generated text.
"""

DISCLAIMER = (
    "This brief is generated automatically from public news coverage and "
    "market data. It is not investment advice. It does not predict future "
    "stock performance or claim any causal link between this launch and "
    "stock price movements."
)


def render_stock_section(snapshot, as_of):
    if snapshot is None:
        return "## Stock Snapshot\n\nStock data unavailable for this run.\n"
    return (
        f"## Stock Snapshot (as of {as_of})\n\n"
        "| Metric | Value |\n"
        "|---|---|\n"
        f"| Current price | ${snapshot['current_price']} |\n"
        f"| 1-year change | {snapshot['pct_change_1y']}% |\n"
        f"| 52-week high | ${snapshot['week52_high']} |\n"
        f"| 52-week low | ${snapshot['week52_low']} |\n"
    )


def render_sources_section(sources):
    if not sources:
        return "## Sources\n\n_No sources recorded._\n"
    lines = "\n".join(f"- {s}" for s in sources)
    return f"## Sources\n\n{lines}\n"


def render_brief(company_name, ticker, generated_date, summary_text, snapshot, sources):
    stock_section = render_stock_section(snapshot, generated_date)
    sources_section = render_sources_section(sources)
    return (
        f"# {company_name} — Product Launch Brief\n\n"
        f"**Ticker:** {ticker} | **Date generated:** {generated_date} | "
        f"**Status:** Confirmed\n\n"
        f"## Launch Summary\n\n{summary_text.strip()}\n\n"
        f"{stock_section}\n"
        f"{sources_section}\n"
        f"---\n\n*{DISCLAIMER}*\n"
    )
