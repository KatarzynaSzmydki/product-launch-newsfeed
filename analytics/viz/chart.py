"""Rule-based chart selection from the shape of a result set.

Phase 6's first half. Which chart suits an answer is a deterministic function of
the result's shape — how many metrics, how many dimensions, and whether one of
them is time — so no LLM is involved and the whole thing is unit-testable
offline.

This module deliberately knows nothing about Streamlit: it returns a
``ChartSpec`` describing *what* to draw, and the caller draws it. That keeps the
rules testable without a browser and leaves the rendering library a swappable
detail.

The rules, in priority order:

    no metrics                      -> none    (nothing to plot)
    no dimensions, single row       -> metric  (a scalar reads best as a big number)
    a time dimension                -> line    (time series wins over any other shape)
    2 metrics x 1 categorical dim   -> scatter (two numerics: plot them against each other)
    1 categorical dimension         -> bar
    anything else                   -> none    (the table is the honest answer)
"""

from __future__ import annotations

from dataclasses import dataclass

from analytics.nl2metric.catalog import is_time_dimension

# Past this many bars the axis is unreadable and the table serves better. The
# spec's limit can legitimately be far higher (MAX_LIMIT is 1000), so this is a
# presentation guard, not a data one.
MAX_BAR_CATEGORIES = 40

NONE = "none"
METRIC = "metric"
LINE = "line"
BAR = "bar"
SCATTER = "scatter"


@dataclass(frozen=True)
class ChartSpec:
    """What to draw. ``kind == NONE`` means the table alone is the answer.

    ``x``/``y`` name result columns. For ``METRIC`` the values live in ``y``
    (one card each) and ``x`` is unused. ``color`` is the series/grouping
    column, set only when a second dimension needs distinguishing.
    """

    kind: str
    x: str | None = None
    y: tuple[str, ...] = ()
    color: str | None = None
    # Why this chart was chosen — surfaced in the UI so the shape rule is visible
    # rather than magic, and useful when a chart looks wrong.
    reason: str = ""

    def __bool__(self) -> bool:
        return self.kind != NONE


def split_columns(
    columns: list[str], metrics: tuple[str, ...] | list[str]
) -> tuple[list[str], list[str]]:
    """Split result columns into (metric columns, dimension columns).

    The spec's metric names are the ground truth: MetricFlow returns one column
    per requested metric under exactly that name, so everything else is a
    grouping column.
    """
    metric_set = set(metrics)
    metric_cols = [c for c in columns if c in metric_set]
    dim_cols = [c for c in columns if c not in metric_set]
    return metric_cols, dim_cols


def choose_chart(
    metric_cols: list[str],
    dim_cols: list[str],
    *,
    row_count: int,
    distinct_counts: dict[str, int] | None = None,
) -> ChartSpec:
    """Pick a chart for a result of this shape.

    ``distinct_counts`` maps a dimension column to its number of distinct
    values; it's only consulted for the bar-width guard, so callers may omit it.
    """
    counts = distinct_counts or {}

    if not metric_cols:
        return ChartSpec(NONE, reason="no metric column to plot")

    metrics = tuple(metric_cols)
    time_dims = [d for d in dim_cols if is_time_dimension(d)]
    cat_dims = [d for d in dim_cols if not is_time_dimension(d)]

    if not dim_cols:
        if row_count == 1:
            return ChartSpec(METRIC, y=metrics, reason="a single row with no breakdown")
        return ChartSpec(NONE, reason="no dimension to plot against")

    # Time wins: a metric over time is a line, even when a category is also
    # present — that just makes it one line per category.
    if time_dims:
        if len(dim_cols) > 2 or len(time_dims) > 1:
            return ChartSpec(NONE, reason="too many dimensions to chart legibly")
        color = cat_dims[0] if cat_dims else None
        if color and len(metrics) > 1:
            # One line per (category, metric) needs a legend the chart can't
            # express from two encodings; the table is clearer.
            return ChartSpec(NONE, reason="multiple metrics split by category over time")
        return ChartSpec(
            LINE, x=time_dims[0], y=metrics, color=color, reason="a metric over time"
        )

    if len(cat_dims) == 1:
        dim = cat_dims[0]
        if len(metrics) == 2:
            return ChartSpec(
                SCATTER,
                x=metrics[0],
                y=(metrics[1],),
                color=dim,
                reason="two numeric metrics, one point per category",
            )
        if counts.get(dim, row_count) > MAX_BAR_CATEGORIES:
            return ChartSpec(NONE, reason=f"more than {MAX_BAR_CATEGORIES} categories to plot")
        return ChartSpec(BAR, x=dim, y=metrics, reason="a metric by category")

    if len(cat_dims) == 2 and len(metrics) == 1:
        return ChartSpec(
            BAR,
            x=cat_dims[0],
            y=metrics,
            color=cat_dims[1],
            reason="one metric across two categories",
        )

    return ChartSpec(NONE, reason="no chart rule fits this result shape")
