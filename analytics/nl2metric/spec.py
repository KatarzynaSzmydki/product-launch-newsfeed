"""The metric-query spec: the small structured object the LLM emits, and the
deterministic validation that gates it before it ever reaches MetricFlow.

This is the load-bearing half of the text-to-metric-query pattern. The model
never writes SQL — it picks metrics/dimensions/filters from the catalog, and
everything here checks that its choices actually exist and are well-formed. A
spec that survives ``validate_spec`` can be rendered to ``mf query`` arguments
by ``to_mf_query_args`` with no further guessing.

Kept in one module (rather than the plan's separate ``validate/`` package) so
the spec type and the rules that judge it stay together; both are pure and
fully unit-testable with no LLM and no database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analytics.nl2metric.catalog import METRIC_TIME, TIME_GRAINS, Catalog, is_time_dimension

# Hard row cap. The validator requires a limit and refuses anything larger, so
# a runaway "select everything" spec can't be compiled. Also the executor's cap.
MAX_LIMIT = 1000

# The only comparison operators a filter may use. "in" takes a list value;
# every other operator takes a scalar.
_OPERATORS = frozenset({"=", "!=", "<", "<=", ">", ">=", "in"})


class SpecError(ValueError):
    """The payload isn't a well-formed spec at all (bad shape / unknown fields)."""


class SpecValidationError(ValueError):
    """The spec is well-formed but references things outside the catalog.

    Carries the full list of problems so the caller (and the LLM, on a retry)
    can see every violation at once rather than one at a time.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class Filter:
    dimension: str  # a catalog dimension name, e.g. "company__sector" or "metric_time"
    operator: str  # one of _OPERATORS
    value: Any  # scalar, or a list when operator == "in"
    grain: str | None = None  # only meaningful for metric_time filters (default "day")

    @classmethod
    def from_dict(cls, data: dict) -> Filter:
        if not isinstance(data, dict):
            raise SpecError(f"each where filter must be an object, got {type(data).__name__}")
        allowed = {"dimension", "operator", "value", "grain"}
        unknown = set(data) - allowed
        if unknown:
            raise SpecError(f"unknown filter field(s): {', '.join(sorted(unknown))}")
        for required in ("dimension", "operator", "value"):
            if required not in data:
                raise SpecError(f"filter is missing required field '{required}'")
        return cls(
            dimension=data["dimension"],
            operator=data["operator"],
            value=data["value"],
            grain=data.get("grain"),
        )

    def is_time(self) -> bool:
        return is_time_dimension(self.dimension)


@dataclass(frozen=True)
class MetricQuerySpec:
    metrics: tuple[str, ...]
    group_by: tuple[str, ...] = ()
    where: tuple[Filter, ...] = ()
    order_by: tuple[str, ...] = ()
    limit: int | None = None
    # Free-text: what the model assumed to turn a fuzzy question into this spec
    # (date window, "confirmed" == multi_sourced, etc.). Surfaced in the UI, not
    # sent to MetricFlow. Never affects validation.
    assumptions: str | None = None

    _ALLOWED_FIELDS = frozenset(
        {"metrics", "group_by", "where", "order_by", "limit", "assumptions"}
    )

    @classmethod
    def from_dict(cls, data: dict) -> MetricQuerySpec:
        """Parse a raw JSON-ish dict into a spec, rejecting anything unexpected.

        This is the structural gate (shape, types, unknown fields). Whether the
        names it references exist is a separate concern — see ``validate_spec``.
        """
        if not isinstance(data, dict):
            raise SpecError(f"spec must be a JSON object, got {type(data).__name__}")

        unknown = set(data) - cls._ALLOWED_FIELDS
        if unknown:
            raise SpecError(f"unknown spec field(s): {', '.join(sorted(unknown))}")

        metrics = _as_str_tuple(data.get("metrics", ()), "metrics")
        if not metrics:
            raise SpecError("spec must name at least one metric")

        group_by = _as_str_tuple(data.get("group_by", ()), "group_by")
        order_by = _as_str_tuple(data.get("order_by", ()), "order_by")

        where_raw = data.get("where", ())
        if not isinstance(where_raw, (list, tuple)):
            raise SpecError("where must be a list of filter objects")
        where = tuple(Filter.from_dict(f) for f in where_raw)

        limit = data.get("limit")
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise SpecError("limit must be an integer")

        assumptions = data.get("assumptions")
        if assumptions is not None and not isinstance(assumptions, str):
            raise SpecError("assumptions must be a string")

        return cls(
            metrics=metrics,
            group_by=group_by,
            where=where,
            order_by=order_by,
            limit=limit,
            assumptions=assumptions,
        )


def _as_str_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise SpecError(f"{field_name} must be a list of strings, not a bare string")
    if not isinstance(value, (list, tuple)):
        raise SpecError(f"{field_name} must be a list of strings")
    for item in value:
        if not isinstance(item, str):
            raise SpecError(f"{field_name} entries must be strings, got {type(item).__name__}")
    return tuple(value)


def parse_spec(data: dict) -> MetricQuerySpec:
    """Shape-level parse only. Raises SpecError; never touches the catalog."""
    return MetricQuerySpec.from_dict(data)


def validate_spec(spec: MetricQuerySpec, catalog: Catalog) -> list[str]:
    """Return a list of violations against the catalog; empty means valid.

    Checks (Phase 4 contract): every metric, group-by, filter dimension and
    order-by key exists in the catalog; a limit is present and within the row
    cap; every filter operator/value is well-formed. MetricFlow owns join and
    grain correctness, so there is deliberately nothing here about SQL.
    """
    errors: list[str] = []

    known_metrics = catalog.metric_names()
    known_dims = catalog.dimension_names()

    for m in spec.metrics:
        if m not in known_metrics:
            errors.append(f"unknown metric '{m}'")

    for g in spec.group_by:
        if g not in known_dims:
            errors.append(f"unknown group_by dimension '{g}'")

    for f in spec.where:
        errors.extend(_validate_filter(f, known_dims))

    # order_by keys must be something the query actually selects: a chosen
    # metric or a group-by dimension (a leading '-' just means descending).
    selectable = set(spec.metrics) | set(spec.group_by)
    for o in spec.order_by:
        key = o[1:] if o.startswith("-") else o
        if key not in selectable:
            errors.append(f"order_by '{o}' is not a selected metric or group_by dimension")

    if spec.limit is None:
        errors.append("limit is required")
    elif spec.limit <= 0:
        errors.append("limit must be a positive integer")
    elif spec.limit > MAX_LIMIT:
        errors.append(f"limit {spec.limit} exceeds the maximum of {MAX_LIMIT}")

    return errors


def _validate_filter(f: Filter, known_dims: set[str]) -> list[str]:
    errors: list[str] = []

    if f.dimension not in known_dims:
        errors.append(f"unknown filter dimension '{f.dimension}'")

    if f.operator not in _OPERATORS:
        errors.append(f"unsupported filter operator '{f.operator}' on '{f.dimension}'")
    elif f.operator == "in":
        if not isinstance(f.value, (list, tuple)) or not f.value:
            errors.append(f"filter on '{f.dimension}' with 'in' needs a non-empty list value")
    elif isinstance(f.value, (list, tuple)):
        errors.append(f"filter on '{f.dimension}' with '{f.operator}' needs a scalar value")

    if f.grain is not None and f.grain not in TIME_GRAINS:
        errors.append(f"unknown time grain '{f.grain}' on filter '{f.dimension}'")

    return errors


def validate_or_raise(spec: MetricQuerySpec, catalog: Catalog) -> MetricQuerySpec:
    errors = validate_spec(spec, catalog)
    if errors:
        raise SpecValidationError(errors)
    return spec


# --- rendering to the mf CLI ------------------------------------------------


def _filter_to_where(f: Filter) -> str:
    """Render one filter as a MetricFlow where fragment (Jinja template form)."""
    if f.is_time():
        # metric_time__quarter carries its grain in the name; a bare metric_time
        # filter defaults to day. The explicit grain field wins if set.
        grain = f.grain
        if grain is None and "__" in f.dimension:
            grain = f.dimension.split("__", 1)[1]
        grain = grain or "day"
        lhs = f"{{{{ TimeDimension('{METRIC_TIME}', '{grain}') }}}}"
    else:
        lhs = f"{{{{ Dimension('{f.dimension}') }}}}"

    if f.operator == "in":
        rendered = ", ".join(_sql_literal(v) for v in f.value)
        return f"{lhs} in ({rendered})"
    return f"{lhs} {f.operator} {_sql_literal(f.value)}"


def _sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def to_mf_query_args(spec: MetricQuerySpec) -> list[str]:
    """Render a validated spec to ``mf query`` CLI arguments.

    Assumes the spec already passed ``validate_spec`` — it renders faithfully
    and does not re-check names.
    """
    args = ["--metrics", ",".join(spec.metrics)]
    if spec.group_by:
        args += ["--group-by", ",".join(spec.group_by)]
    for f in spec.where:
        args += ["--where", _filter_to_where(f)]
    if spec.order_by:
        args += ["--order", ",".join(spec.order_by)]
    if spec.limit is not None:
        args += ["--limit", str(spec.limit)]
    return args
