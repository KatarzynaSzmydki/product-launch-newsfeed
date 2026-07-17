"""Spec parsing + validation: the deterministic gate that stands between the
LLM and MetricFlow. These are the Phase 4 "invalid specs are rejected, valid
ones pass" tests."""

from __future__ import annotations

import pytest

from analytics.nl2metric.spec import (
    MAX_LIMIT,
    Filter,
    MetricQuerySpec,
    SpecError,
    parse_spec,
    to_mf_query_args,
    validate_spec,
)

# --- parsing (shape / unknown fields) --------------------------------------


def test_parse_minimal_spec():
    spec = parse_spec({"metrics": ["launch_count"], "limit": 10})
    assert spec.metrics == ("launch_count",)
    assert spec.limit == 10
    assert spec.group_by == ()


def test_parse_rejects_unknown_top_level_field():
    with pytest.raises(SpecError, match="unknown spec field"):
        parse_spec({"metrics": ["launch_count"], "limit": 10, "columns": ["x"]})


def test_parse_rejects_unknown_filter_field():
    with pytest.raises(SpecError, match="unknown filter field"):
        parse_spec(
            {
                "metrics": ["launch_count"],
                "limit": 10,
                "where": [
                    {"dimension": "company__sector", "operator": "=", "value": "IT", "op": "="}
                ],
            }
        )


def test_parse_requires_at_least_one_metric():
    with pytest.raises(SpecError, match="at least one metric"):
        parse_spec({"metrics": [], "limit": 10})


def test_parse_rejects_bare_string_metrics():
    with pytest.raises(SpecError, match="not a bare string"):
        parse_spec({"metrics": "launch_count", "limit": 10})


def test_parse_rejects_non_integer_limit():
    with pytest.raises(SpecError, match="limit must be an integer"):
        parse_spec({"metrics": ["launch_count"], "limit": "10"})


def test_parse_rejects_bool_limit():
    # bool is an int subclass; a JSON true must not sneak through as limit=1.
    with pytest.raises(SpecError, match="limit must be an integer"):
        parse_spec({"metrics": ["launch_count"], "limit": True})


def test_parse_reads_filters_and_assumptions():
    flt = {"dimension": "metric_time", "operator": ">=", "value": "2025-01-01", "grain": "day"}
    spec = parse_spec(
        {
            "metrics": ["launch_count"],
            "where": [flt],
            "limit": 10,
            "assumptions": "since 2025",
        }
    )
    assert spec.where[0] == Filter("metric_time", ">=", "2025-01-01", "day")
    assert spec.assumptions == "since 2025"


# --- validation against the catalog ----------------------------------------


def test_valid_spec_has_no_errors(catalog):
    spec = parse_spec(
        {
            "metrics": ["launch_count"],
            "group_by": ["company__sector", "metric_time__quarter"],
            "where": [{"dimension": "company__sector", "operator": "=", "value": "IT"}],
            "order_by": ["-launch_count"],
            "limit": 20,
        }
    )
    assert validate_spec(spec, catalog) == []


def test_unknown_metric_rejected(catalog):
    spec = parse_spec({"metrics": ["revenue"], "limit": 10})
    assert any("unknown metric 'revenue'" in e for e in validate_spec(spec, catalog))


def test_unknown_group_by_rejected(catalog):
    spec = parse_spec({"metrics": ["launch_count"], "group_by": ["company__ceo"], "limit": 10})
    errors = validate_spec(spec, catalog)
    assert any("unknown group_by dimension 'company__ceo'" in e for e in errors)


def test_unknown_filter_dimension_rejected(catalog):
    spec = parse_spec(
        {
            "metrics": ["launch_count"],
            "where": [{"dimension": "company__ceo", "operator": "=", "value": "x"}],
            "limit": 10,
        }
    )
    assert any("unknown filter dimension 'company__ceo'" in e for e in validate_spec(spec, catalog))


def test_missing_limit_rejected(catalog):
    spec = parse_spec({"metrics": ["launch_count"]})
    assert "limit is required" in validate_spec(spec, catalog)


def test_over_cap_limit_rejected(catalog):
    spec = parse_spec({"metrics": ["launch_count"], "limit": MAX_LIMIT + 1})
    assert any("exceeds the maximum" in e for e in validate_spec(spec, catalog))


def test_non_positive_limit_rejected(catalog):
    spec = parse_spec({"metrics": ["launch_count"], "limit": 0})
    assert any("positive integer" in e for e in validate_spec(spec, catalog))


def test_bad_operator_rejected(catalog):
    spec = parse_spec(
        {
            "metrics": ["launch_count"],
            "where": [{"dimension": "company__sector", "operator": "LIKE", "value": "%IT%"}],
            "limit": 10,
        }
    )
    assert any("unsupported filter operator" in e for e in validate_spec(spec, catalog))


def test_in_operator_requires_list(catalog):
    spec = parse_spec(
        {
            "metrics": ["launch_count"],
            "where": [{"dimension": "company__sector", "operator": "in", "value": "IT"}],
            "limit": 10,
        }
    )
    assert any("needs a non-empty list" in e for e in validate_spec(spec, catalog))


def test_scalar_operator_rejects_list(catalog):
    spec = parse_spec(
        {
            "metrics": ["launch_count"],
            "where": [{"dimension": "company__sector", "operator": "=", "value": ["IT", "Health"]}],
            "limit": 10,
        }
    )
    assert any("needs a scalar value" in e for e in validate_spec(spec, catalog))


def test_bad_time_grain_rejected(catalog):
    flt = {"dimension": "metric_time", "operator": ">=", "value": "2025", "grain": "fortnight"}
    spec = parse_spec(
        {
            "metrics": ["launch_count"],
            "where": [flt],
            "limit": 10,
        }
    )
    assert any("unknown time grain 'fortnight'" in e for e in validate_spec(spec, catalog))


def test_order_by_must_be_selected(catalog):
    spec = parse_spec(
        {"metrics": ["launch_count"], "order_by": ["-avg_launch_day_move"], "limit": 10}
    )
    assert any("is not a selected metric or group_by" in e for e in validate_spec(spec, catalog))


def test_metric_time_dimensions_are_known(catalog):
    # metric_time and its grains are always valid dimensions, even though they
    # aren't named per semantic model.
    spec = parse_spec(
        {"metrics": ["launch_count"], "group_by": ["metric_time__month"], "limit": 10}
    )
    assert validate_spec(spec, catalog) == []


# --- rendering to mf CLI args ----------------------------------------------


def test_render_basic_args():
    spec = MetricQuerySpec(
        metrics=("launch_count",),
        group_by=("company__sector",),
        order_by=("-launch_count",),
        limit=5,
    )
    args = to_mf_query_args(spec)
    assert args == [
        "--metrics", "launch_count",
        "--group-by", "company__sector",
        "--order", "-launch_count",
        "--limit", "5",
    ]


def test_render_categorical_where():
    spec = MetricQuerySpec(
        metrics=("launch_count",),
        where=(Filter("company__sector", "=", "Information Technology"),),
        limit=10,
    )
    args = to_mf_query_args(spec)
    assert "--where" in args
    where = args[args.index("--where") + 1]
    assert where == "{{ Dimension('company__sector') }} = 'Information Technology'"


def test_render_time_where_uses_time_dimension():
    spec = MetricQuerySpec(
        metrics=("launch_count",),
        where=(Filter("metric_time", ">=", "2025-01-01", "day"),),
        limit=10,
    )
    args = to_mf_query_args(spec)
    where = args[args.index("--where") + 1]
    assert where == "{{ TimeDimension('metric_time', 'day') }} >= '2025-01-01'"


def test_render_grain_inferred_from_dimension_name():
    spec = MetricQuerySpec(
        metrics=("launch_count",),
        where=(Filter("metric_time__quarter", ">=", "2025-01-01"),),
        limit=10,
    )
    args = to_mf_query_args(spec)
    where = args[args.index("--where") + 1]
    assert "TimeDimension('metric_time', 'quarter')" in where


def test_render_in_clause_and_quote_escaping():
    spec = MetricQuerySpec(
        metrics=("launch_count",),
        where=(Filter("company__company_name", "in", ["Alphabet", "O'Reilly"]),),
        limit=10,
    )
    args = to_mf_query_args(spec)
    where = args[args.index("--where") + 1]
    assert where == "{{ Dimension('company__company_name') }} in ('Alphabet', 'O''Reilly')"
