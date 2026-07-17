"""Shared fixtures: a small in-memory catalog so the spec/generate tests don't
depend on a freshly parsed dbt manifest."""

from __future__ import annotations

import pytest

from analytics.nl2metric.catalog import Catalog, DimensionInfo, MetricInfo


def _dim(name: str, entity: str, dtype: str = "categorical") -> DimensionInfo:
    return DimensionInfo(
        name=name, type=dtype, description=None, entity=entity, semantic_model=entity
    )


@pytest.fixture
def catalog() -> Catalog:
    metrics = (
        MetricInfo("launch_count", "simple", "Launch count", "Distinct launches."),
        MetricInfo("confirmation_rate", "ratio", None, "Share multi-sourced."),
        MetricInfo("avg_launch_day_move", "simple", None, "Avg 1-day move."),
    )
    dimensions = (
        _dim("company__sector", "company"),
        _dim("company__company_name", "company"),
        _dim("launch__category", "launch"),
    )
    return Catalog(metrics=metrics, dimensions=dimensions)
