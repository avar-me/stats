"""Telegram channel subscriber snapshots via Bot API getChatMemberCount."""

from __future__ import annotations

from collectors.base import CollectResult, Context, Entity, Source, SourceError, SourceNotConfigured
from core.http import HttpError
from core.model import Observation, stamp
from core.redact import redact

API = "https://api.telegram.org"


class TelegramChannelsSource(Source):
    id = "telegram_channels"
    title = "Telegram-каналы"
    hint = "Секрет TELEGRAM_BOT_TOKEN. Бот должен иметь доступ к каналу: используется getChatMemberCount."

    def entities(self, block: dict) -> list[Entity]:
        entities = []
        for channel in block.get("channels") or []:
            if not channel.get("enabled", True):
                continue
            username = str(channel["username"]).lstrip("@")
            entities.append(Entity(username, channel.get("title") or f"@{username}", f"https://t.me/{username}"))
        return entities

    def collect(self, ctx: Context) -> CollectResult:
        token = (ctx.env.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            raise SourceNotConfigured("Нужен секрет TELEGRAM_BOT_TOKEN. Бот должен иметь доступ к каналу.")
        channels = self.entities(ctx.config)
        if not channels:
            raise SourceNotConfigured("В config.yaml нет включённых telegram_channels.")
        result = CollectResult()
        collected_at = stamp(ctx.now)
        day = ctx.now.date().isoformat()
        for channel in channels:
            try:
                count = _member_count(ctx.client, token, channel.id)
            except HttpError as error:
                result.entity_errors[channel.id] = redact(str(error))
                continue
            result.observations.append(Observation(
                source=self.id,
                entity=channel.id,
                metric="subscribers",
                date=day,
                value=count,
                unit="subscribers",
                aggregation="snapshot",
                collected_at=collected_at,
                status="confirmed",
                revision=collected_at,
            ))
        if not result.observations and result.entity_errors:
            details = "; ".join(f"{key}: {value}" for key, value in result.entity_errors.items())
            raise SourceError(f"Ни один канал не ответил. {details}")
        return result


def _member_count(client, token: str, username: str) -> int:
    url = f"{API}/bot{token}/getChatMemberCount?chat_id=@{username}"
    response = client.request("GET", url, timeout=20)
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("ok"):
        description = payload.get("description", "Telegram API error") if isinstance(payload, dict) else "Telegram API error"
        raise HttpError(redact(str(description)))
    return int(payload["result"])
