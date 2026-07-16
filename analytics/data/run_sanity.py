"""Run analytics/data/sanity_queries.sql against analytics.duckdb and print
each labelled result. Uses the duckdb Python package (already a dependency), so
no separate duckdb CLI install is needed.

    python -m analytics.data.run_sanity
"""

from __future__ import annotations

from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "analytics.duckdb"
SQL_PATH = HERE / "sanity_queries.sql"


def _statements(sql_text: str):
    """Yield (label, sql) for each ';'-terminated statement.

    The label is the last `-- ...` comment line preceding the statement; comment
    lines are stripped from the executed SQL.
    """
    for chunk in sql_text.split(";"):
        lines = chunk.splitlines()
        label = "query"
        sql_lines = []
        for line in lines:
            if line.strip().startswith("--"):
                label = line.strip().lstrip("-").strip()
            else:
                sql_lines.append(line)
        sql = "\n".join(sql_lines).strip()
        if sql:
            yield label, sql


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(
            f"{DB_PATH.name} not found — run `python -m analytics.data.generate_data` first."
        )
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        for label, sql in _statements(SQL_PATH.read_text(encoding="utf-8")):
            print(f"== {label} ==")
            res = con.execute(sql)
            cols = [d[0] for d in res.description]
            print("   " + " | ".join(cols))
            for row in res.fetchall():
                print("   " + " | ".join("" if v is None else str(v) for v in row))
            print()
    finally:
        con.close()


if __name__ == "__main__":
    main()
