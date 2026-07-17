"""Metric/dimension catalog loaded from dbt's semantic manifest.

The catalog is the ground truth the NL->metric-query prompt (Phase 4) injects so
the LLM can only ever reference metrics and dimensions that actually exist. We
read the compiled ``target/semantic_manifest.json`` rather than shelling out to
``mf list`` on every request: it's the same data MetricFlow uses, but offline,
deterministic, and fast enough to call per request.

Regenerate the manifest after any semantic-model YAML change:

    dbt parse --project-dir analytics/dbt --profiles-dir analytics/dbt
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Grains MetricFlow exposes on the special ``metric_time`` dimension. Group by
# ``metric_time__<grain>``; filter on ``metric_time``.
TIME_GRAINS = ["day", "week", "month", "quarter", "year"]

_DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1] / "dbt" / "target" / "semantic_manifest.json"
)


@dataclass(frozen=True)
class MetricInfo:
    name: str
    type: str
    label: str | None
    description: str | None


@dataclass(frozen=True)
class DimensionInfo:
    # Qualified name the LLM must emit for grouping, e.g. "company__sector".
    name: str
    type: str  # "categorical" | "time"
    description: str | None
    entity: str  # linking entity (the qualifier before "__")
    semantic_model: str


@dataclass(frozen=True)
class Catalog:
    metrics: tuple[MetricInfo, ...]
    dimensions: tuple[DimensionInfo, ...]

    def metric_names(self) -> set[str]:
        return {m.name for m in self.metrics}

    def dimension_names(self) -> set[str]:
        names = {d.name for d in self.dimensions}
        names.add("metric_time")
        names.update(f"metric_time__{g}" for g in TIME_GRAINS)
        return names

    def to_prompt_block(self) -> str:
        """Render a compact catalog block for the NL->spec prompt."""
        lines: list[str] = [f"METRICS ({len(self.metrics)}):"]
        for m in self.metrics:
            desc = f" — {m.description}" if m.description else ""
            lines.append(f"- {m.name} ({m.type}){desc}")

        lines.append("")
        lines.append("DIMENSIONS (group_by / where):")
        by_entity: dict[str, list[DimensionInfo]] = {}
        for d in self.dimensions:
            by_entity.setdefault(d.entity, []).append(d)
        for entity in sorted(by_entity):
            lines.append(f"  via {entity}:")
            for d in sorted(by_entity[entity], key=lambda x: x.name):
                desc = f" — {d.description}" if d.description else ""
                lines.append(f"  - {d.name} ({d.type}){desc}")

        lines.append("")
        lines.append("TIME:")
        lines.append(
            "- metric_time — group by metric_time__{grain} "
            f"(grain in {', '.join(TIME_GRAINS)}); filter on metric_time."
        )
        return "\n".join(lines)


def _primary_entity(semantic_model: dict) -> str | None:
    for entity in semantic_model.get("entities", []):
        if entity.get("type") == "primary":
            return entity["name"]
    return semantic_model.get("primary_entity")


def load_catalog(manifest_path: str | Path | None = None) -> Catalog:
    path = Path(manifest_path) if manifest_path else _DEFAULT_MANIFEST
    if not path.exists():
        raise FileNotFoundError(
            f"Semantic manifest not found at {path}. Run "
            "`dbt parse --project-dir analytics/dbt --profiles-dir analytics/dbt` first."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))

    metrics = tuple(
        MetricInfo(
            name=m["name"],
            type=m["type"],
            label=m.get("label"),
            description=m.get("description"),
        )
        for m in sorted(manifest.get("metrics", []), key=lambda x: x["name"])
    )

    dimensions: list[DimensionInfo] = []
    for sm in manifest.get("semantic_models", []):
        entity = _primary_entity(sm)
        if entity is None:
            continue
        for dim in sm.get("dimensions", []):
            # Time dimensions are queried through metric_time, not by name.
            if dim.get("type") == "time":
                continue
            dimensions.append(
                DimensionInfo(
                    name=f"{entity}__{dim['name']}",
                    type=dim.get("type", "categorical"),
                    description=dim.get("description"),
                    entity=entity,
                    semantic_model=sm["name"],
                )
            )

    return Catalog(metrics=metrics, dimensions=tuple(dimensions))


if __name__ == "__main__":
    print(load_catalog().to_prompt_block())
