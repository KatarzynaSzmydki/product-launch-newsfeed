"""Runner tests. The pure helpers run always; the end-to-end query runs only
when a built DuckDB file and the mf CLI are present (skipped in CI-without-data
and on a fresh checkout)."""

from __future__ import annotations

import pytest

from analytics.nl2metric.runner import (
    _DEFAULT_DUCKDB,
    QueryExecutionError,
    _extract_sql,
    _read_csv,
    find_mf_binary,
    run_spec,
)
from analytics.nl2metric.spec import MetricQuerySpec


def test_find_mf_binary_honours_override():
    assert find_mf_binary("/custom/mf") == "/custom/mf"


def test_extract_sql_after_header():
    out = "🔎 SQL (remove --explain to see data):\nSELECT 1\nFROM t\n"
    assert _extract_sql(out) == "SELECT 1\nFROM t"


def test_extract_sql_without_header_returns_body():
    assert _extract_sql("SELECT 1") == "SELECT 1"


def test_extract_sql_empty_is_none():
    assert _extract_sql("   \n  ") is None


def test_read_csv_handles_mf_double_cr_endings(tmp_path):
    # mf writes '\r\r\n' line endings; the parser must not emit phantom rows.
    path = tmp_path / "out.csv"
    path.write_bytes(b"company__sector,launch_count\r\r\nComm,10\r\r\nIT,6\r\r\n")
    columns, rows = _read_csv(str(path))
    assert columns == ["company__sector", "launch_count"]
    assert rows == [
        {"company__sector": "Comm", "launch_count": "10"},
        {"company__sector": "IT", "launch_count": "6"},
    ]


def test_read_csv_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")
    assert _read_csv(str(path)) == ([], [])


def test_run_spec_errors_when_duckdb_missing(tmp_path):
    spec = MetricQuerySpec(metrics=("launch_count",), limit=5)
    with pytest.raises(QueryExecutionError, match="DuckDB file not found"):
        run_spec(spec, duckdb_path=tmp_path / "nope.duckdb")


def _mf_available() -> bool:
    try:
        find_mf_binary()
        return True
    except QueryExecutionError:
        return False


@pytest.mark.skipif(
    not _DEFAULT_DUCKDB.exists() or not _mf_available(),
    reason="needs a built analytics.duckdb and the mf CLI (run generate_data + dbt build)",
)
def test_run_spec_executes_a_real_query():
    spec = MetricQuerySpec(
        metrics=("launch_count",),
        group_by=("company__sector",),
        order_by=("-launch_count",),
        limit=10,
    )
    result = run_spec(spec, explain=True)
    assert "launch_count" in [c.lower() for c in result.columns] or any(
        "launch_count" in c.lower() for c in result.columns
    )
    assert result.row_count >= 1
    assert result.latency_ms is not None
    # --explain should have captured some SQL for the trace.
    assert result.compiled_sql and "select" in result.compiled_sql.lower()
