"""Sticker pack metadata. Installation counts are not available and are not invented."""

from __future__ import annotations

from collections import Counter

from collectors.base import CollectResult, Context, Entity, Source, SourceError, SourceNotConfigured
from core.catalog import INSTALLS_UNAVAILABLE
from core.http import HttpError
from core.model import Observation, stamp
from core.redact import redact

API = "https://api.telegram.org"


class TelegramStickersSource(Source):
    id = "telegram_stickers"
    title = "Стикерпаки"
    hint = "Тот же TELEGRAM_BOT_TOKEN. getStickerSet отдаёт состав набора и не отдаёт установки."

    def entities(self, block: dict) -> list[Entity]:
        entities = []
        for pack in block.get("packs") or []:
            if not pack.get("enabled", True):
                continue
            name = str(pack["name"])
            entities.append(Entity(name, pack.get("title") or name, f"https://t.me/addstickers/{name}"))
        return entities

    def collect(self, ctx: Context) -> CollectResult:
        token = (ctx.env.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            raise SourceNotConfigured("Нужен секрет TELEGRAM_BOT_TOKEN для getStickerSet.")
        packs = self.entities(ctx.config)
        if not packs:
            raise SourceNotConfigured("В config.yaml нет включённых стикерпаков.")
        result = CollectResult()
        collected_at = stamp(ctx.now)
        day = ctx.now.date().isoformat()
        for pack in packs:
            try:
                payload = _sticker_set(ctx.client, token, pack.id)
            except HttpError as error:
                result.entity_errors[pack.id] = redact(str(error))
                continue
            stickers = payload.get("stickers") or []
            emojis = _emoji_preview(stickers)
            result.observations.append(Observation(
                source=self.id,
                entity=pack.id,
                metric="sticker_count",
                date=day,
                value=len(stickers),
                unit="stickers",
                aggregation="snapshot",
                collected_at=collected_at,
                status="confirmed",
                revision=collected_at,
            ))
            result.entity_info[pack.id] = {
                "title": payload.get("title") or pack.title,
                "url": pack.link,
                "sticker_type": payload.get("sticker_type") or "",
                "emojis": emojis,
                "stickers": str(len(stickers)),
                "installs_note": INSTALLS_UNAVAILABLE,
            }
        if not result.observations and result.entity_errors:
            details = "; ".join(f"{key}: {value}" for key, value in result.entity_errors.items())
            raise SourceError(f"Ни один стикерпак не прочитан. {details}")
        return result


def _sticker_set(client, token: str, name: str) -> dict:
    url = f"{API}/bot{token}/getStickerSet?name={name}"
    response = client.request("GET", url, timeout=20)
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("ok") or not isinstance(payload.get("result"), dict):
        description = payload.get("description", "Telegram API error") if isinstance(payload, dict) else "Telegram API error"
        raise HttpError(redact(str(description)))
    return payload["result"]


def _emoji_preview(stickers: list) -> str:
    counts: Counter[str] = Counter()
    for sticker in stickers:
        emoji = str(sticker.get("emoji") or "").strip()
        if emoji:
            counts[emoji] += 1
    return " ".join(emoji for emoji, _count in counts.most_common(12))
