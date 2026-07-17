"""NL question -> validated metric-query spec.

The one place the LLM is involved. It builds the prompt, calls the swappable
``LLMClient``, extracts the JSON object the model returned, parses it into a
``MetricQuerySpec`` and validates it against the catalog. The model's output is
treated as untrusted: anything that isn't a clean, catalog-consistent spec
raises rather than reaching MetricFlow.

The LLM boundary is a plain ``LLMClient`` argument, so tests inject a fake and
the whole path runs offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from analytics.llm.client import LLMClient
from analytics.nl2metric.catalog import Catalog
from analytics.nl2metric.prompt import build_prompt
from analytics.nl2metric.spec import (
    MetricQuerySpec,
    SpecError,
    SpecValidationError,
    parse_spec,
    validate_or_raise,
)


class GenerationError(RuntimeError):
    """The model's reply couldn't be turned into a valid spec.

    Wraps the three ways generation fails: no JSON found, the model explicitly
    declined (``{"error": ...}``), or the parsed spec failed validation. The raw
    reply is kept for debugging / the UI trace.
    """

    def __init__(self, message: str, *, raw: str, errors: list[str] | None = None) -> None:
        self.raw = raw
        self.errors = errors or []
        super().__init__(message)


@dataclass(frozen=True)
class Generation:
    spec: MetricQuerySpec
    raw: str  # the model's full reply, for the "show your work" trace


def generate_spec(question: str, catalog: Catalog, client: LLMClient) -> Generation:
    """Turn a question into a validated spec, or raise GenerationError."""
    prompt = build_prompt(question, catalog)
    raw = client.generate(prompt)

    data = _extract_json_object(raw)
    if data is None:
        raise GenerationError("model did not return a JSON object", raw=raw)

    # The contract lets the model refuse a question it can't express.
    if isinstance(data, dict) and "error" in data and "metrics" not in data:
        raise GenerationError(str(data["error"]), raw=raw)

    try:
        spec = parse_spec(data)
        validate_or_raise(spec, catalog)
    except SpecValidationError as exc:
        raise GenerationError(
            f"model produced an invalid spec: {exc}", raw=raw, errors=exc.errors
        ) from exc
    except SpecError as exc:
        raise GenerationError(f"model produced a malformed spec: {exc}", raw=raw) from exc

    return Generation(spec=spec, raw=raw)


def _extract_json_object(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply.

    Tolerates the common wrappers: a ```json fenced block, or prose around a
    single ``{...}`` object. Returns None if nothing parseable is found.
    """
    if not text:
        return None

    candidate = _strip_code_fence(text.strip())

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost balanced {...} span.
    span = _first_balanced_object(candidate)
    if span is None:
        return None
    try:
        parsed = json.loads(span)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop the opening ``` (optionally ```json) and a matching closing fence.
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
