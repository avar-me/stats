"""Normalized observations. Missing numbers stay missing; they are never stored as zero."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = frozenset({"confirmed", "estimated", "delayed", "unavailable"})
AGGREGATIONS = frozenset({"daily", "snapshot", "period"})
FORBIDDEN_DIMENSIONS = frozenset({
    "user",
    "user_id",
    "username",
    "query",
    "ip",
    "text",
    "message",
    "phone",
    "hash",
    "user_hash",
})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime | None = None) -> str:
    current = moment or utcnow()
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Observation:
    source: str
    entity: str
    metric: str
    date: str
    value: float | None
    unit: str
    aggregation: str
    collected_at: str
    status: str
    dimensions: dict[str, str] = field(default_factory=dict)
    revision: str = ""

    def __post_init__(self) -> None:
        if not self.source or not self.entity or not self.metric:
            raise ValueError("source, entity and metric are required")
        if not DATE_RE.match(self.date):
            raise ValueError(f"date must be YYYY-MM-DD, got {self.date!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status}")
        if self.aggregation not in AGGREGATIONS:
            raise ValueError(f"unknown aggregation {self.aggregation}")
        if self.value is not None:
            number = float(self.value)
            if not math.isfinite(number):
                raise ValueError("value must be finite or null")
            self.value = number
        clean: dict[str, str] = {}
        for key, raw in self.dimensions.items():
            name = str(key).strip()
            if name.lower() in FORBIDDEN_DIMENSIONS:
                raise ValueError(f"dimension {name} is not allowed in public statistics")
            clean[name] = str(raw).strip()
        self.dimensions = dict(sorted(clean.items()))
        if not self.revision:
            self.revision = self.collected_at

    @property
    def key(self) -> str:
        dims = ",".join(f"{key}={value}" for key, value in self.dimensions.items())
        return f"{self.source}|{self.entity}|{self.metric}|{self.date}|{dims}"

    @property
    def series_id(self) -> str:
        dims = "|".join(f"{key}={value}" for key, value in self.dimensions.items())
        base = f"{self.source}|{self.entity}|{self.metric}"
        return f"{base}|{dims}" if dims else base

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "entity": self.entity,
            "metric": self.metric,
            "date": self.date,
            "value": self.value,
            "unit": self.unit,
            "aggregation": self.aggregation,
            "collected_at": self.collected_at,
            "status": self.status,
            "dimensions": dict(self.dimensions),
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Observation:
        return cls(
            source=raw["source"],
            entity=raw["entity"],
            metric=raw["metric"],
            date=raw["date"],
            value=raw["value"],
            unit=raw["unit"],
            aggregation=raw["aggregation"],
            collected_at=raw["collected_at"],
            status=raw["status"],
            dimensions=dict(raw.get("dimensions") or {}),
            revision=raw.get("revision") or raw["collected_at"],
        )


def json_number(value: float | None) -> int | float | None:
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return round(float(value), 4)
