#!/usr/bin/env python3
"""Write clearly marked sample JSON for layout work.

Output goes to site/preview-data and is not the published dashboard.
Open site/index.html?preview=1
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collectors.registry import SOURCES
from core.aggregate import build_public
from core.config import load_config
from core.model import Observation, stamp
from core.store import HistoryStore

NOW = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)


def main() -> None:
    root = ROOT
    store = HistoryStore(root / "site" / "preview-data")
    collected = stamp(NOW)
    observations = []
    for offset, subscribers in ((0, 1280), (7, 1240), (30, 1100)):
        observations.append(_snap("telegram_channels", "avarlangme", "subscribers", subscribers, offset, collected))
    for offset in range(0, 14):
        observations.append(_flow("cloudflare", "avar.me", "page_views", 100 + offset, offset, collected, "views"))
        observations.append(_flow("cloudflare", "avar.me", "visits", 40 + offset, offset, collected, "visits"))
        observations.append(_flow("cloudflare", "avar.me", "http_requests", 900 + offset * 3, offset, collected, "requests"))
    observations.append(Observation(
        source="cloudflare", entity="avar.me", metric="page_views", date="2026-11-16",
        value=80, unit="views", aggregation="daily", collected_at=collected, status="confirmed",
        dimensions={"country": "RU"}, revision=collected,
    ))
    observations.append(Observation(
        source="telegram_stickers", entity="AvarMe", metric="sticker_count", date="2026-11-16",
        value=24, unit="stickers", aggregation="snapshot", collected_at=collected, status="confirmed",
        revision=collected,
    ))
    for source_id in {item.source for item in observations}:
        store.merge(source_id, [item for item in observations if item.source == source_id])
        store.record_run(source_id, state="ok", attempted_at=collected, records=1, success=True, entity_info={
            "AvarMe": {
                "title": "Хӏарпик",
                "url": "https://t.me/addstickers/AvarMe",
                "emojis": "📖 ☀️",
                "installs_note": "Статистика установок недоступна через Telegram API",
            },
        } if source_id == "telegram_stickers" else {})
    summary, history = build_public(store, load_config(root / "config.yaml"), [item() for item in SOURCES], NOW)
    summary["preview"] = True
    history["preview"] = True
    destination = root / "site" / "preview-data"
    destination.mkdir(parents=True, exist_ok=True)
    _write(destination / "summary.json", summary)
    _write(destination / "history.json", history)
    print("Демонстрационные данные записаны в site/preview-data.")
    print("Откройте site/index.html?preview=1 — это не статистика проекта и не попадает в публикацию.")


def _snap(source, entity, metric, value, days_ago, collected):
    day = (NOW.date() - timedelta(days=days_ago)).isoformat()
    return Observation(
        source=source, entity=entity, metric=metric, date=day, value=value, unit="subscribers",
        aggregation="snapshot", collected_at=collected, status="confirmed", revision=collected,
    )


def _flow(source, entity, metric, value, days_ago, collected, unit):
    day = (NOW.date() - timedelta(days=days_ago)).isoformat()
    return Observation(
        source=source, entity=entity, metric=metric, date=day, value=value, unit=unit,
        aggregation="daily", collected_at=collected, status="confirmed", revision=collected,
    )


def _write(path: Path, payload: dict) -> None:
    import json
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
