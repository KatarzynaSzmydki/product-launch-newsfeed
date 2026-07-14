"""CLI: the single call the routine's agent turn makes per confirmed
launch. Renders the brief from staged facts + generated prose, gates it,
writes it, records it in state.json, and clears the staging file.

This exists as one command rather than four (render -> validate -> mark ->
delete) because every separate tool call the agent makes re-sends the whole
conversation to the model. Folding the sequence into one entrypoint also
keeps data/state.json out of the agent's context entirely -- it is read and
written here, in-process, instead of being hand-edited.

Validation runs against the in-memory markdown, so a brief that fails the
gate is never written to disk at all and its staging file survives for the
next run.

Usage:
    python -m src.publish_brief data/pending_generation/<id>.json \
        --summary "<generated prose>"
    python -m src.publish_brief data/pending_generation/<id>.json \
        --summary-file <path>
"""
import argparse
import json
import re
import sys
from pathlib import Path

from . import state as state_module
from . import validate_brief
from .brief_template import render_brief

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / "data" / "state.json"
BRIEFS_DIR = REPO_ROOT / "data" / "briefs"


def brief_filename(staged):
    """data/briefs/<date>_<TICKER>_<keyword>.md -- derived here rather than
    passed in, so the agent cannot drift from the naming convention app.py
    and the existing briefs rely on.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", staged["keyword"].lower()).strip("-")
    return f"{staged['today']}_{staged['ticker']}_{slug}.md"


def write_price_sidecar(output_path, staged):
    """A price series has no home in the brief markdown (code-owned, clean
    template) or state.json (must stay small) -- so it's a sidecar keyed off
    the brief's own filename, written only when the snapshot has one (older
    snapshot shapes / a missing snapshot just mean no sparkline, not an error).
    """
    snapshot = staged.get("stock_snapshot") or {}
    series = snapshot.get("price_series")
    if not series:
        return
    sidecar_path = output_path.with_suffix(".prices.json")
    sidecar_path.write_text(
        json.dumps({"as_of": staged["today"], "series": series}),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("staging_file", help="Path to a data/pending_generation/<id>.json file")
    summary_source = parser.add_mutually_exclusive_group(required=True)
    summary_source.add_argument("--summary", help="Generated launch-summary prose")
    summary_source.add_argument(
        "--summary-file",
        help="File holding the prose, for summaries long enough that shell quoting gets fragile",
    )
    args = parser.parse_args()

    staging_path = Path(args.staging_file)
    staged = json.loads(staging_path.read_text(encoding="utf-8"))

    summary = (
        args.summary
        if args.summary is not None
        else Path(args.summary_file).read_text(encoding="utf-8")
    )

    brief_markdown = render_brief(
        company_name=staged["company_name"],
        ticker=staged["ticker"],
        generated_date=staged["today"],
        summary_text=summary,
        snapshot=staged.get("stock_snapshot"),
        sources=[a["source_name"] or a["url"] for a in staged["articles"]],
    )

    snippets = [a.get("snippet", "") for a in staged.get("articles", [])]
    errors = validate_brief.validate_text(brief_markdown, snippets)
    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        print(
            f"NOT PUBLISHED: {staging_path} left in place for a later run.",
            file=sys.stderr,
        )
        sys.exit(1)

    output_path = BRIEFS_DIR / brief_filename(staged)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(brief_markdown, encoding="utf-8")
    write_price_sidecar(output_path, staged)

    brief_rel = output_path.relative_to(REPO_ROOT).as_posix()
    current_state = state_module.load_state(STATE_PATH)
    state_module.mark_generated(
        current_state, staged["group_key"], brief_rel, staged["today"]
    )
    state_module.save_state(STATE_PATH, current_state)

    staging_path.unlink()
    print(f"PUBLISHED {brief_rel}")


if __name__ == "__main__":
    main()
