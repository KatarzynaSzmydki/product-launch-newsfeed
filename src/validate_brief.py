"""Deterministic gate a generated brief must pass before it's committed
to the public repo. Nothing here calls an LLM -- generation runs
unattended inside a scheduled routine with no human review, so this is
the mechanical check that stands in for one.

Usage:
    python -m src.validate_brief data/briefs/<file>.md --staging data/pending_generation/<id>.json
Exits non-zero (and prints FAIL lines) if the brief should not be published.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from .brief_template import DISCLAIMER

BANNED_PHRASES = re.compile(
    r"(price target|forecast(ed|s)?|expected to (rise|fall|climb|drop|surge|plunge)|"
    r"will (rise|jump|surge|soar|plunge|fall)|because of the launch|due to the launch|"
    r"as a result of the launch|likely to (rise|fall|climb|drop))",
    re.IGNORECASE,
)


def check_disclaimer(text):
    return DISCLAIMER in text


def check_banned_phrases(text):
    match = BANNED_PHRASES.search(text)
    return match.group(0) if match else None


def check_verbatim_overlap(text, snippets, min_words=15):
    """Crude plagiarism check: flags any run of `min_words` consecutive
    words from a staged source snippet appearing verbatim in the brief.
    """
    brief_words = re.findall(r"\w+", text.lower())
    brief_joined = " ".join(brief_words)
    for snippet in snippets:
        words = re.findall(r"\w+", snippet.lower())
        for i in range(len(words) - min_words + 1):
            span = " ".join(words[i : i + min_words])
            if span and span in brief_joined:
                return span
    return None


def validate(brief_path, staging_path=None):
    text = Path(brief_path).read_text(encoding="utf-8")
    errors = []

    if not check_disclaimer(text):
        errors.append("missing required disclaimer text")

    banned = check_banned_phrases(text)
    if banned:
        errors.append(f"contains banned phrase: {banned!r}")

    if staging_path and Path(staging_path).exists():
        staged = json.loads(Path(staging_path).read_text(encoding="utf-8"))
        snippets = [a.get("snippet", "") for a in staged.get("articles", [])]
        overlap = check_verbatim_overlap(text, snippets)
        if overlap:
            errors.append(f"verbatim overlap with source snippet: {overlap!r}")

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("brief_path")
    parser.add_argument(
        "--staging", help="Matching data/pending_generation/<id>.json, for the plagiarism check"
    )
    args = parser.parse_args()

    errors = validate(args.brief_path, args.staging)
    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
