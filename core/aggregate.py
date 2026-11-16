"""Build the public dashboard documents from stored observations."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from core.catalog import MetricSpec, metrics_for, unavailable_for
from core.model import json_number
from core.store import HistoryStore

PUBLIC_DIMENSIONS = frozenset({"country", "device", "command"})
PERIOD_DIMENSIONS = frozenset({"path", "referrer"})


def build_public(store: HistoryStore, config: dict, sources: list, now: datetime) -> tuple[dict, dict]:
    freshness = timedelta(hours=int(config.get("freshness_hours", 36)))
    cards: list[dict] = []
    source_blocks: list[dict] = []
    series: dict[str, list[dict]] = {}

    for source in sources:
        block = config.get("sources", {}).get(source.id, {})
        enabled = bool(block.get("enabled", False))
        document = store.load(source.id)
        meta = document["meta"]
        status = _display_status(enabled, meta, now, freshness)
        grouped = _group(document["observations"].values())
        source_entities = source.entities(block)
        entity_ids = {entity.id for entity in source_entities}
        # Flow windows end on the newest day any site reported. A site that stopped
        # reporting then shows an empty window instead of its old numbers as "last 7 days".
        source_ends: dict[str, str] = {}
        for (entity_id, metric, dims), points in grouped.items():
            if entity_id in entity_ids and not dims and points and points[-1].get("aggregation") != "period":
                source_ends[metric] = max(source_ends.get(metric, ""), points[-1]["date"])
        entities = []
        for entity in source_entities:
            metrics = []
            breakdowns = []
            for spec in metrics_for(source.id, available_only=True):
                points = grouped.get((entity.id, spec.metric, ()), [])
                summary = _summarize(spec, points, source_ends.get(spec.metric))
                summary["series"] = f"{source.id}|{entity.id}|{spec.metric}"
                metrics.append(summary)
                public_points = _public_points(points) if spec.chart else []
                if public_points:
                    series[summary["series"]] = public_points
                for (dimension_name, dimension_value), dim_points in _dimension_groups(grouped, entity.id, spec.metric):
                    if dimension_name not in PUBLIC_DIMENSIONS or spec.kind == "period":
                        continue
                    series_id = f"{source.id}|{entity.id}|{spec.metric}|{dimension_name}={dimension_value}"
                    series[series_id] = _public_points(dim_points)
                breakdowns.extend(_latest_breakdown(spec, grouped, entity.id))
            info = (meta.get("entity_info") or {}).get(entity.id) or {}
            entities.append({
                "id": entity.id,
                "title": entity.title,
                "link": entity.link,
                "note": (meta.get("entity_errors") or {}).get(entity.id),
                "info": _public_info(info),
                "metrics": metrics,
                "breakdowns": breakdowns,
            })
        source_blocks.append({
            "id": source.id,
            "title": source.title,
            "enabled": enabled,
            "status": status,
            "last_success": meta.get("last_success"),
            "last_attempt": meta.get("last_attempt"),
            "note": _source_message(enabled, meta, status),
            "hint": getattr(source, "hint", ""),
            "warnings": list(meta.get("warnings") or []),
            "unavailable": [
                {"metric": spec.metric, "label": spec.label, "definition": spec.definition}
                for spec in unavailable_for(source.id)
            ],
            "entities": entities,
        })
        cards.extend(_overview_cards(source, entities, status, meta.get("last_success")))

    generated = _stamp(now)
    summary = {
        "generated_at": generated,
        "preview": False,
        "freshness_hours": int(config.get("freshness_hours", 36)),
        "ranges": ["7d", "30d", "90d", "1y", "all"],
        "cards": cards,
        "sources": source_blocks,
    }
    history = {"generated_at": generated, "preview": False, "series": series}
    return strip_private(summary), strip_private(history)


def _group(observations) -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = {}
    for raw in observations:
        if raw.get("value") is None:
            continue
        dims = tuple(sorted((raw.get("dimensions") or {}).items()))
        if raw.get("aggregation") == "period":
            grouped.setdefault((raw["entity"], raw["metric"], dims), []).append(raw)
            continue
        if dims:
            grouped.setdefault((raw["entity"], raw["metric"], dims), []).append(raw)
        else:
            grouped.setdefault((raw["entity"], raw["metric"], ()), []).append(raw)
    for points in grouped.values():
        points.sort(key=lambda item: item["date"])
    return grouped


def _dimension_groups(grouped: dict, entity: str, metric: str):
    for (ent, met, dims), points in grouped.items():
        if ent != entity or met != metric or len(dims) != 1:
            continue
        if points and points[0].get("aggregation") == "period":
            continue
        yield dims[0], points


def _latest_breakdown(spec: MetricSpec, grouped: dict, entity: str) -> list[dict]:
    period_rows = []
    for (ent, met, dims), points in grouped.items():
        if ent != entity or met != spec.metric or not points:
            continue
        if points[-1].get("aggregation") != "period" or len(dims) != 1:
            continue
        if dims[0][0] not in PERIOD_DIMENSIONS:
            continue
        period_rows.append((points[-1]["date"], dims[0][0], dims[0][1], points[-1]))
    if not period_rows:
        return []
    latest_date = max(row[0] for row in period_rows)
    buckets: dict[str, list] = {}
    for row_date, name, value, point in period_rows:
        if row_date != latest_date:
            continue
        buckets.setdefault(name, []).append({
            "label": value,
            "value": json_number(point["value"]),
            "status": point["status"],
        })
    breakdowns = []
    for name, rows in buckets.items():
        rows.sort(key=lambda item: item["value"] or 0, reverse=True)
        breakdowns.append({
            "metric": spec.metric,
            "dimension": name,
            "as_of": latest_date,
            "rows": rows[:20],
        })
    return breakdowns


def _summarize(spec: MetricSpec, points: list[dict], end: str | None = None) -> dict:
    base = {
        "metric": spec.metric,
        "label": spec.label,
        "definition": spec.definition,
        "unit": spec.unit,
        "kind": spec.kind,
        "latest": None,
        "latest_date": None,
        "latest_status": None,
        "delta_7d": None,
        "delta_7d_from": None,
        "delta_30d": None,
        "delta_30d_from": None,
        "window_7d": None,
        "window_30d": None,
    }
    if not points:
        return base
    latest = points[-1]
    base["latest"] = json_number(latest["value"])
    base["latest_date"] = latest["date"]
    base["latest_status"] = latest["status"]
    if spec.kind in {"snapshot", "level"}:
        delta_7, from_7 = _delta(points, latest, 7)
        delta_30, from_30 = _delta(points, latest, 30)
        base["delta_7d"] = json_number(delta_7)
        base["delta_7d_from"] = from_7
        base["delta_30d"] = json_number(delta_30)
        base["delta_30d_from"] = from_30
    elif spec.kind == "flow":
        window_end = end or latest["date"]
        base["window_7d"] = _window(points, window_end, 7)
        base["window_30d"] = _window(points, window_end, 30)
    return base


def _delta(points: list[dict], latest: dict, days: int) -> tuple[float | None, str | None]:
    target = date.fromisoformat(latest["date"]) - timedelta(days=days)
    prior = [point for point in points if date.fromisoformat(point["date"]) <= target]
    if not prior:
        return None, None
    previous = prior[-1]
    if previous["date"] == latest["date"]:
        return None, None
    return float(latest["value"]) - float(previous["value"]), previous["date"]


def _window(points: list[dict], end: str, days: int) -> dict | None:
    end_date = date.fromisoformat(end)
    start = end_date - timedelta(days=days - 1)
    chosen = [point for point in points if start <= date.fromisoformat(point["date"]) <= end_date]
    if not chosen:
        return None
    return {
        "sum": json_number(sum(float(point["value"]) for point in chosen)),
        "days_present": len(chosen),
        "days_expected": days,
        "start": start.isoformat(),
        "end": end,
        # Private: which days carried data. Removed before publishing.
        "_dates": sorted({point["date"] for point in chosen}),
    }


def strip_private(value):
    if isinstance(value, dict):
        return {key: strip_private(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [strip_private(item) for item in value]
    return value


def _overview_cards(source, entities: list[dict], status: str, updated_at: str | None) -> list[dict]:
    cards = []
    for spec in metrics_for(source.id, available_only=True):
        if not spec.primary:
            continue
        metric_rows = []
        for entity in entities:
            match = next((item for item in entity["metrics"] if item["metric"] == spec.metric), None)
            if match is not None:
                metric_rows.append(match)
        present = [row for row in metric_rows if row["latest"] is not None]
        # Flow value is the newest day only: a site whose last day is older is not
        # added to today's total. Its numbers still appear in the 7/30-day windows.
        newest = max((row["latest_date"] for row in present), default=None)
        day_rows = [row for row in present if spec.kind != "flow" or row["latest_date"] == newest]
        value = None
        partial = False
        if day_rows:
            value = json_number(sum(float(row["latest"]) for row in day_rows))
            partial = len(day_rows) < len(entities)
        card = {
            "id": f"{source.id}.{spec.metric}",
            "source": source.id,
            "title": spec.label,
            "source_title": source.title,
            "definition": spec.definition,
            "unit": spec.unit,
            "kind": spec.kind,
            "status": status,
            "value": value,
            "partial": partial,
            "entities_with_value": len(day_rows),
            "entities": len(entities),
            "as_of": max(row["latest_date"] for row in day_rows) if day_rows else None,
            "updated_at": updated_at,
            "href": f"#source-{source.id}",
            "delta_7d": None,
            "delta_7d_from": None,
            "delta_30d": None,
            "delta_30d_from": None,
            "window_7d": None,
            "window_30d": None,
        }
        if spec.kind in {"snapshot", "level"} and present and all(row["delta_7d"] is not None for row in present):
            card["delta_7d"] = json_number(sum(row["delta_7d"] for row in present))
            card["delta_7d_from"] = min(row["delta_7d_from"] for row in present)
        if spec.kind in {"snapshot", "level"} and present and all(row["delta_30d"] is not None for row in present):
            card["delta_30d"] = json_number(sum(row["delta_30d"] for row in present))
            card["delta_30d_from"] = min(row["delta_30d_from"] for row in present)
        if spec.kind == "flow":
            windows_7d = [row["window_7d"] for row in metric_rows if row["window_7d"]]
            windows_30d = [row["window_30d"] for row in metric_rows if row["window_30d"]]
            card["window_7d"] = _merge_windows(windows_7d) if windows_7d else None
            card["window_30d"] = _merge_windows(windows_30d) if windows_30d else None
        cards.append(card)
    if not any(spec.primary and spec.available for spec in metrics_for(source.id)):
        return cards
    return cards


def _merge_windows(windows: list[dict]) -> dict:
    # A day counts once if any site reported it. Sites with sparse traffic do not
    # shrink the count for busy sites, and missing days are not filled with zeros.
    days = sorted({day for window in windows for day in window["_dates"]})
    return {
        "sum": json_number(sum(window["sum"] for window in windows)),
        "days_present": len(days),
        "days_expected": windows[0]["days_expected"],
        "start": windows[0]["start"],
        "end": windows[0]["end"],
        "_dates": days,
    }


def _public_points(points: list[dict]) -> list[dict]:
    return [
        {"date": point["date"], "value": json_number(point["value"]), "status": point["status"]}
        for point in points
        if point.get("aggregation") != "period"
    ]


def _public_info(info: dict) -> dict:
    allowed = ("title", "url", "sticker_type", "emojis", "installs_note", "stickers")
    return {key: info[key] for key in allowed if key in info and info[key] not in (None, "")}


def _display_status(enabled: bool, meta: dict, now: datetime, freshness: timedelta) -> str:
    if not enabled:
        return "disabled"
    state = meta.get("state")
    last_success = _parse(meta.get("last_success"))
    if state == "not_configured":
        return "stale" if last_success else "not_configured"
    if state == "error":
        return "stale" if last_success else "error"
    if state == "ok" and last_success is not None:
        age = now.astimezone(timezone.utc) - last_success
        return "stale" if age > freshness else "ok"
    if last_success is not None:
        return "stale"
    return "not_configured"


def _source_message(enabled: bool, meta: dict, status: str) -> str | None:
    if not enabled:
        return "Модуль подключён. Источник выключен в config.yaml и включается без изменений кода."
    if meta.get("last_error"):
        return meta["last_error"]
    if status == "stale" and meta.get("state") == "ok":
        return "Данные старше обычного суточного обновления."
    return None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
