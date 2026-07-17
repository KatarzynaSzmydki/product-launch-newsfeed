"""Executes a validated spec against MetricFlow and returns rows.

This is the "MetricFlow disposes" end of the pattern. It renders the spec to
``mf query`` arguments and shells out to the CLI — the interface the free,
local MetricFlow exposes (there's no hosted API here; see PROJECT_PLAN §6). The
subprocess runs in the dbt project dir with an absolute DuckDB path, a wall-clock
timeout, and a hard row cap, and writes results to a temp CSV we parse back.

Metric queries compile to SELECTs only — MetricFlow never emits DDL/DML — so the
connection is effectively read-only by construction; the timeout and row cap are
the belt-and-braces limits the plan calls for.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from analytics.nl2metric.catalog import Catalog
from analytics.nl2metric.spec import (
    MAX_LIMIT,
    MetricQuerySpec,
    to_mf_query_args,
    validate_or_raise,
    with_defaults,
)

_ANALYTICS_ROOT = Path(__file__).resolve().parents[1]
_DBT_DIR = _ANALYTICS_ROOT / "dbt"
_DEFAULT_DUCKDB = _ANALYTICS_ROOT / "data" / "analytics.duckdb"

DEFAULT_TIMEOUT_S = 60


class QueryExecutionError(RuntimeError):
    """The mf subprocess failed, timed out, or returned unparseable output."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, str]]
    compiled_sql: str | None = None
    latency_ms: float | None = None
    args: list[str] = field(default_factory=list)  # the mf query args used, for the trace

    @property
    def row_count(self) -> int:
        return len(self.rows)


def find_mf_binary(override: str | None = None) -> str:
    """Locate the ``mf`` CLI: explicit override, then next to the running
    interpreter (same venv), then PATH."""
    if override:
        return override
    env_override = os.environ.get("MF_BIN")
    if env_override:
        return env_override
    bindir = Path(sys.executable).parent
    for name in ("mf.exe", "mf"):
        candidate = bindir / name
        if candidate.exists():
            return str(candidate)
    found = shutil.which("mf")
    if found:
        return found
    raise QueryExecutionError(
        "could not find the `mf` CLI. Install dbt-metricflow "
        "(pip install -r analytics/requirements.txt) or set MF_BIN."
    )


def _mf_env(duckdb_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    # mf reads the profile from the project dir and resolves the DuckDB `path`
    # relative to its own cwd, so hand it an absolute path (see README).
    env["DBT_PROFILES_DIR"] = "."
    env["DBT_DUCKDB_PATH"] = str(duckdb_path)
    env["PYTHONIOENCODING"] = "utf-8"  # Windows consoles default to cp125x and crash on symbols
    return env


def run_spec(
    spec: MetricQuerySpec,
    *,
    catalog: Catalog | None = None,
    duckdb_path: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    row_cap: int = MAX_LIMIT,
    explain: bool = False,
    mf_bin: str | None = None,
) -> QueryResult:
    """Compile and run a spec via MetricFlow.

    Pass ``catalog`` to re-validate defensively before running (the executor
    assumes the spec is already validated otherwise). ``explain=True`` adds a
    second dry-run pass that captures the compiled SQL for the UI trace.
    """
    if catalog is not None:
        validate_or_raise(spec, catalog)

    capped = with_defaults(spec, default_limit=row_cap)
    if capped.limit is None or capped.limit > row_cap:
        capped = replace(capped, limit=row_cap)

    db = Path(duckdb_path) if duckdb_path else _DEFAULT_DUCKDB
    if not db.exists():
        raise QueryExecutionError(
            f"DuckDB file not found at {db}. Build it first: "
            "python -m analytics.data.generate_data && dbt build "
            "--project-dir analytics/dbt --profiles-dir analytics/dbt."
        )

    mf = find_mf_binary(mf_bin)
    env = _mf_env(db.resolve())
    query_args = to_mf_query_args(capped)

    fd, csv_path = tempfile.mkstemp(suffix=".csv", prefix="mfq_")
    os.close(fd)
    try:
        cmd = [mf, "query", *query_args, "--csv", csv_path]
        start = time.perf_counter()
        proc = _run(cmd, env, timeout)
        latency_ms = (time.perf_counter() - start) * 1000
        if proc.returncode != 0:
            raise QueryExecutionError(
                f"mf query failed (exit {proc.returncode}):\n{proc.stderr or proc.stdout}".strip()
            )
        columns, rows = _read_csv(csv_path)
    finally:
        _unlink_quietly(csv_path)

    compiled_sql = _explain(mf, query_args, env, timeout) if explain else None

    return QueryResult(
        columns=columns,
        rows=rows,
        compiled_sql=compiled_sql,
        latency_ms=latency_ms,
        args=query_args,
    )


def _run(cmd: list[str], env: dict[str, str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            cwd=_DBT_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise QueryExecutionError(f"mf query timed out after {timeout}s") from exc


def _read_csv(path: str) -> tuple[list[str], list[dict[str, str]]]:
    # mf writes '\r\r\n' line endings; left as-is, csv.reader treats the extra
    # CR as a phantom blank record between every data row. Strip CRs first.
    with open(path, encoding="utf-8") as fh:
        text = fh.read().replace("\r", "")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], []
    rows = [dict(zip(header, record)) for record in reader if record]
    return header, rows


def _explain(mf: str, query_args: list[str], env: dict[str, str], timeout: int) -> str | None:
    """Second dry-run pass to capture the compiled SQL. Best-effort — a failure
    here never sinks a successful data query."""
    proc = _run([mf, "query", *query_args, "--explain"], env, timeout)
    if proc.returncode != 0:
        return None
    return _extract_sql(proc.stdout)


def _extract_sql(explain_output: str) -> str | None:
    """Pull the SQL body out of `mf query --explain` stdout.

    The CLI prints a header line mentioning "SQL" followed by the statement; take
    everything after that line."""
    lines = explain_output.splitlines()
    for i, line in enumerate(lines):
        if "SQL" in line and line.rstrip().endswith(":"):
            body = "\n".join(lines[i + 1 :]).strip()
            return body or None
    stripped = explain_output.strip()
    return stripped or None


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
