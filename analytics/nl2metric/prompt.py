"""Assembles the NL->spec prompt: role, the live catalog block, the strict JSON
output contract, and a few worked examples.

The catalog block is injected from ``Catalog.to_prompt_block()`` so the model is
only ever shown metrics and dimensions that actually exist — the first line of
defence before the validator. The examples are hand-written against the real
launches/companies/stock catalog and double as documentation of the spec shape.
"""

from __future__ import annotations

from analytics.nl2metric.catalog import Catalog
from analytics.nl2metric.spec import MAX_LIMIT

_ROLE = """\
You translate a plain-English analytics question about NASDAQ-100 product \
launches into a METRIC-QUERY SPEC — a small JSON object. You never write SQL. \
A downstream semantic layer (MetricFlow) compiles your spec into correct SQL, \
so your only job is to pick the right metrics, dimensions and filters from the \
catalog below."""

_CONTRACT = f"""\
OUTPUT CONTRACT — respond with exactly one JSON object and nothing else:

{{
  "metrics":     [string, ...],   // one or more metric names from the catalog (required)
  "group_by":    [string, ...],   // dimension names to break the metric down by (optional)
  "where":       [                // filters (optional)
    {{"dimension": string, "operator": string, "value": scalar|list, "grain": string?}}
  ],
  "order_by":    [string, ...],   // a selected metric or group_by name; prefix "-" for descending (optional)
  "limit":       integer,         // REQUIRED, 1..{MAX_LIMIT}
  "assumptions": string           // one sentence: what you assumed to build this spec (optional but encouraged)
}}

RULES:
- Use ONLY metric and dimension names that appear in the catalog. Never invent one.
- Time is queried through metric_time: group by metric_time__{{grain}} (day/week/month/quarter/year);
  filter with dimension "metric_time" and a "grain", e.g.
  {{"dimension": "metric_time", "operator": ">=", "value": "2025-01-01", "grain": "day"}}.
- operator is one of: =, !=, <, <=, >, >=, in. Use "in" only with a list value.
- Always set a limit. If the user asks for a ranking / "top N", set limit to N and order_by the metric descending.
- Put any interpretation you had to make (date window, what "confirmed" means, etc.) in "assumptions".
- If the question cannot be expressed with these metrics and dimensions, respond with:
  {{"error": "why it can't be answered with the available catalog"}}"""

_EXAMPLES = """\
EXAMPLES

Q: How many confirmed launches did each sector have this year?
{"metrics": ["launch_count"], "group_by": ["company__sector", "metric_time__year"], "limit": 100, "assumptions": "Counted all launches grouped by year; 'this year' shown per-year rather than filtered."}

Q: Which companies launched the most products? Top 5.
{"metrics": ["launch_count"], "group_by": ["company__company_name"], "order_by": ["-launch_count"], "limit": 5}

Q: What's the average 1-day stock move on launch days by sector?
{"metrics": ["avg_launch_day_move"], "group_by": ["company__sector"], "limit": 100}

Q: Confirmation rate for IT companies.
{"metrics": ["confirmation_rate"], "group_by": ["company__sector"], "where": [{"dimension": "company__sector", "operator": "=", "value": "Information Technology"}], "limit": 100}

Q: Launches per quarter since the start of 2025.
{"metrics": ["launch_count"], "group_by": ["metric_time__quarter"], "where": [{"dimension": "metric_time", "operator": ">=", "value": "2025-01-01", "grain": "day"}], "order_by": ["metric_time__quarter"], "limit": 100}"""


def build_prompt(question: str, catalog: Catalog) -> str:
    """Assemble the full NL->spec prompt for one question."""
    return "\n\n".join(
        [
            _ROLE,
            "CATALOG",
            catalog.to_prompt_block(),
            _CONTRACT,
            _EXAMPLES,
            f"Q: {question.strip()}",
        ]
    )
