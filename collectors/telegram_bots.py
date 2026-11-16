"""Read aggregated bot telemetry. The Bot API does not provide this history.

The file or URL must already be counters. Raw user ids, usernames, message text
and queries are ignored even if a producer accidentally includes them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from collectors.base import CollectResult, Context, Entity, Source, SourceError, SourceNotConfigured
from core.model import Observation, stamp
from core.redact import redact

_EVENT = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_DAY_FIELDS = (
    ("requests", "requests", "requests"),
    ("successful_requests", "successful_requests", "requests"),
    ("failed_requests", "failed_requests", "requests"),
    ("unique_users", "unique_users", "users"),
    ("duration_ms_sum", "duration_ms_sum", "milliseconds"),
    ("duration_count", "duration_count", "requests"),
)


class TelegramBotsSource(Source):
    id = "telegram_bots"
    title = "Telegram-боты"
    hint = (
        "Включите sources.telegram_bots.enabled и передайте TELEMETRY_FILE или TELEMETRY_URL. "
        "Счётчики пишет integrations/telegram_bot_analytics.py либо tgcloud-модуль integrations/tgcloud. "
        "Bot API историю использования не отдаёт."
    )

    def entities(self, block: dict) -> list[Entity]:
        entities = []
        for bot in block.get("bots") or []:
            if not bot.get("enabled", True):
                continue
            name = str(bot["name"]).lstrip("@")
            entities.append(Entity(name, bot.get("title") or f"@{name}", f"https://t.me/{name}"))
        return entities

    def collect(self, ctx: Context) -> CollectResult:
        payload = _load(ctx)
        allowed = {entity.id for entity in self.entities(ctx.config)}
        if not allowed:
            raise SourceNotConfigured("В config.yaml нет включённых ботов.")
        observations = parse_telemetry(payload, collected_at=stamp(ctx.now), allowed_bots=allowed)
        return CollectResult(observations=observations)


def parse_telemetry(payload: dict, *, collected_at: str, allowed_bots: set[str]) -> list[Observation]:
    if not isinstance(payload, dict):
        raise SourceError("Телеметрия должна быть JSON-объектом")
    observations: list[Observation] = []
    for bot_row in payload.get("bots") or []:
        if not isinstance(bot_row, dict):
            continue
        name = str(bot_row.get("bot") or "").lstrip("@")
        if name not in allowed_bots:
            continue
        for day_row in bot_row.get("days") or []:
            if not isinstance(day_row, dict):
                continue
            day = str(day_row.get("date") or "")
            if len(day) != 10:
                continue
            for field, metric, unit in _DAY_FIELDS:
                if field not in day_row or day_row[field] is None:
                    continue
                observations.append(_obs(name, metric, day, day_row[field], unit, collected_at, "daily"))
            for command, count in (day_row.get("commands") or {}).items():
                if count is None or not _EVENT.fullmatch(str(command)):
                    continue
                observations.append(_obs(
                    name, "command_requests", day, count, "requests", collected_at, "daily", {"command": str(command)},
                ))
        for month_row in bot_row.get("months") or []:
            if not isinstance(month_row, dict) or month_row.get("unique_users") is None:
                continue
            month = str(month_row.get("month") or "")
            if not re.fullmatch(r"\d{4}-\d{2}", month):
                continue
            observations.append(_obs(
                name,
                "unique_users_monthly",
                f"{month}-01",
                month_row["unique_users"],
                "users",
                collected_at,
                "period",
            ))
    return observations


def _load(ctx: Context) -> dict:
    url = (ctx.env.get("TELEMETRY_URL") or "").strip()
    if url:
        headers = {}
        token = (ctx.env.get("TELEMETRY_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = ctx.client.request("GET", url, headers=headers, timeout=30)
            payload = response.json()
        except Exception as error:
            raise SourceError(f"Не удалось прочитать TELEMETRY_URL: {redact(str(error))}") from error
        if not isinstance(payload, dict):
            raise SourceError("TELEMETRY_URL вернул не объект")
        return payload
    raw_path = (ctx.env.get("TELEMETRY_FILE") or "").strip()
    if not raw_path:
        raise SourceNotConfigured(
            "Нужен TELEMETRY_FILE или TELEMETRY_URL с уже агрегированными счётчиками. "
            "Формат пишет integrations/telegram_bot_analytics.py."
        )
    path = Path(raw_path)
    if not path.is_absolute():
        path = ctx.root / path
    if not path.is_file():
        raise SourceNotConfigured("Файл агрегированной телеметрии ещё не создан.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SourceError("Файл телеметрии не является JSON") from error
    if not isinstance(payload, dict):
        raise SourceError("Файл телеметрии должен содержать объект")
    return payload


def _obs(entity, metric, day, value, unit, collected_at, aggregation, dimensions=None) -> Observation:
    return Observation(
        source="telegram_bots",
        entity=entity,
        metric=metric,
        date=day,
        value=float(value),
        unit=unit,
        aggregation=aggregation,
        collected_at=collected_at,
        status="confirmed",
        dimensions=dimensions or {},
        revision=collected_at,
    )
