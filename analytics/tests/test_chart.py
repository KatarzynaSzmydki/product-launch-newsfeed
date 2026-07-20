"""Chart selection is a pure function of result shape, so every rule is testable
without Streamlit, a browser, or a database."""

from __future__ import annotations

from analytics.viz.chart import (
    BAR,
    LINE,
    MAX_BAR_CATEGORIES,
    METRIC,
    NONE,
    SCATTER,
    choose_chart,
    split_columns,
)


def test_split_columns_uses_spec_metrics_as_truth():
    metric_cols, dim_cols = split_columns(
        ["company__sector", "launch_count"], ("launch_count",)
    )
    assert metric_cols == ["launch_count"]
    assert dim_cols == ["company__sector"]


def test_single_scalar_is_a_metric_card():
    chart = choose_chart(["launch_count"], [], row_count=1)
    assert chart.kind == METRIC
    assert chart.y == ("launch_count",)


def test_several_metrics_one_row_is_several_cards():
    chart = choose_chart(["launch_count", "confirmation_rate"], [], row_count=1)
    assert chart.kind == METRIC
    assert chart.y == ("launch_count", "confirmation_rate")


def test_no_metric_column_plots_nothing():
    assert choose_chart([], ["company__sector"], row_count=5).kind == NONE


def test_time_dimension_is_a_line():
    chart = choose_chart(["launch_count"], ["metric_time__month"], row_count=24)
    assert chart.kind == LINE
    assert chart.x == "metric_time__month"
    assert chart.color is None


def test_time_plus_category_is_a_line_per_category():
    chart = choose_chart(
        ["launch_count"], ["metric_time__quarter", "company__sector"], row_count=40
    )
    assert chart.kind == LINE
    assert chart.x == "metric_time__quarter"
    assert chart.color == "company__sector"


def test_time_beats_category_when_both_present():
    """A category alongside time must not demote the result to a bar chart."""
    chart = choose_chart(
        ["launch_count"], ["company__sector", "metric_time__month"], row_count=40
    )
    assert chart.kind == LINE


def test_category_is_a_bar():
    chart = choose_chart(["launch_count"], ["company__sector"], row_count=11)
    assert chart.kind == BAR
    assert chart.x == "company__sector"
    assert chart.y == ("launch_count",)


def test_two_metrics_by_category_is_a_scatter():
    chart = choose_chart(
        ["launch_count", "avg_launch_day_move"], ["company__sector"], row_count=11
    )
    assert chart.kind == SCATTER
    assert chart.x == "launch_count"
    assert chart.y == ("avg_launch_day_move",)
    assert chart.color == "company__sector"


def test_two_categories_one_metric_is_a_grouped_bar():
    chart = choose_chart(
        ["launch_count"], ["company__sector", "launch__category"], row_count=30
    )
    assert chart.kind == BAR
    assert chart.x == "company__sector"
    assert chart.color == "launch__category"


def test_too_many_bars_falls_back_to_the_table():
    dim = "company__company_name"
    chart = choose_chart(
        ["launch_count"],
        [dim],
        row_count=200,
        distinct_counts={dim: MAX_BAR_CATEGORIES + 1},
    )
    assert chart.kind == NONE


def test_bar_survives_at_the_category_limit():
    dim = "company__company_name"
    chart = choose_chart(
        ["launch_count"], [dim], row_count=40, distinct_counts={dim: MAX_BAR_CATEGORIES}
    )
    assert chart.kind == BAR


def test_three_dimensions_plot_nothing():
    chart = choose_chart(
        ["launch_count"],
        ["company__sector", "launch__category", "metric_time__year"],
        row_count=50,
    )
    assert chart.kind == NONE


def test_many_rows_without_a_dimension_plot_nothing():
    assert choose_chart(["launch_count"], [], row_count=7).kind == NONE


def test_chartspec_is_falsy_when_there_is_nothing_to_draw():
    assert not choose_chart([], [], row_count=0)
    assert choose_chart(["launch_count"], ["company__sector"], row_count=5)


def test_every_spec_explains_itself():
    for chart in (
        choose_chart(["launch_count"], [], row_count=1),
        choose_chart(["launch_count"], ["company__sector"], row_count=5),
        choose_chart([], [], row_count=0),
    ):
        assert chart.reason
