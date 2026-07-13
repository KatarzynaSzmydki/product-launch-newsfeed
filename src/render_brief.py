"""CLI: assemble a brief markdown file from staged facts + a generated
launch-summary paragraph. This is what the routine's agent turn calls
after it writes the summary prose -- disclaimer/stock-section/sources
formatting stays code-owned; --summary is the only free-text input.

Usage:
    python -m src.render_brief data/pending_generation/<id>.json \
        --summary "<generated prose>" \
        --output data/briefs/<date>_<ticker>_<keyword>.md
"""
import argparse
import json
from pathlib import Path

from .brief_template import render_brief


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("staging_file", help="Path to a data/pending_generation/<id>.json file")
    parser.add_argument("--summary", required=True, help="Generated launch-summary prose")
    parser.add_argument("--output", required=True, help="Output path for the brief markdown")
    args = parser.parse_args()

    staged = json.loads(Path(args.staging_file).read_text(encoding="utf-8"))

    brief_markdown = render_brief(
        company_name=staged["company_name"],
        ticker=staged["ticker"],
        generated_date=staged["today"],
        summary_text=args.summary,
        snapshot=staged.get("stock_snapshot"),
        sources=[a["source_name"] or a["url"] for a in staged["articles"]],
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(brief_markdown, encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
