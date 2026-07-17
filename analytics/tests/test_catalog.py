"""Catalog loader tests.

Most run against a tiny inline manifest so they don't depend on a freshly
parsed dbt project. One smoke test loads the real manifest when present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analytics.nl2metric.catalog import (
    TIME_GRAINS,
    load_catalog,
)
from analytics.nl2metric.catalog import (
    _DEFAULT_MANIFEST as REAL_MANIFEST,
)

_FIXTURE = {
    "metrics": [
        {"name": "launch_count", "type": "simple", "label": "Launch count", "description": "Launches."},
        {"name": "confirmation_rate", "type": "ratio", "label": None, "description": "Share."},
    ],
    "semantic_models": [
        {
            "name": "launches",
            "primary_entity": None,
            "entities": [
                {"name": "launch", "type": "primary"},
                {"name": "company", "type": "foreign"},
            ],
            "dimensions": [
                {"name": "launch_date", "type": "time"},
                {"name": "category", "type": "categorical", "description": "Cat."},
            ],
        },
        {
            "name": "companies",
            "primary_entity": None,
            "entities": [{"name": "company", "type": "primary"}],
            "dimensions": [{"name": "sector", "type": "categorical", "description": "Sector."}],
        },
    ],
}


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    p = tmp_path / "semantic_manifest.json"
    p.write_text(json.dumps(_FIXTURE), encoding="utf-8")
    return p


def test_metrics_loaded_and_sorted(manifest_path: Path):
    cat = load_catalog(manifest_path)
    assert [m.name for m in cat.metrics] == ["confirmation_rate", "launch_count"]
    assert cat.metric_names() == {"launch_count", "confirmation_rate"}


def test_dimensions_qualified_by_primary_entity(manifest_path: Path):
    cat = load_catalog(manifest_path)
    names = {d.name for d in cat.dimensions}
    assert names == {"launch__category", "company__sector"}


def test_time_dimensions_excluded_from_named_dims(manifest_path: Path):
    cat = load_catalog(manifest_path)
    # launch_date is a time dimension: reached via metric_time, never listed by name.
    assert all("launch_date" not in d.name for d in cat.dimensions)


def test_metric_time_grains_in_dimension_names(manifest_path: Path):
    cat = load_catalog(manifest_path)
    dims = cat.dimension_names()
    assert "metric_time" in dims
    for grain in TIME_GRAINS:
        assert f"metric_time__{grain}" in dims


def test_prompt_block_mentions_every_metric_and_dimension(manifest_path: Path):
    block = load_catalog(manifest_path).to_prompt_block()
    for token in ("launch_count", "confirmation_rate", "company__sector", "launch__category", "metric_time"):
        assert token in block


def test_missing_manifest_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_catalog(tmp_path / "nope.json")


@pytest.mark.skipif(not REAL_MANIFEST.exists(), reason="run `dbt parse` to generate the manifest")
def test_real_manifest_has_expected_core_metrics():
    cat = load_catalog()
    assert {"launch_count", "confirmation_rate", "avg_launch_day_move"} <= cat.metric_names()
    assert "company__sector" in cat.dimension_names()
