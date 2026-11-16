"""Privacy-preserving counters for a bot process.

track_event() never raises. It stores counts, not messages. Unique users use one
HMAC key for both the day and the month, so a person who returns tomorrow stays
one monthly user. Daily hashes are not rotated and then unioned.

Retention: event ids and daily user hashes — 40 days; monthly hashes — 400 days.
Only the aggregate export is safe to publish. The sqlite file stays out of git.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_EVENT = __import__("re").compile(r"^[A-Za-z0-9_.:-]{1,64}$")
DAY_RETENTION = 40
MONTH_RETENTION = 400


def track_event(
    *,
    bot: str,
    event: str,
    success: bool,
    duration_ms: int | float | None = None,
    user_id: str | int | None = None,
    event_id: str | None = None,
    db_path: str | Path | None = None,
    secret: str | None = None,
    now: datetime | None = None,
) -> None:
    try:
        _record(
            bot=bot,
            event=event,
            success=bool(success),
            duration_ms=duration_ms,
            user_id=None if user_id is None else str(user_id),
            event_id=None if event_id is None else str(event_id),
            db_path=Path(db_path) if db_path else _default_db(),
            secret=secret if secret is not None else os.environ.get("ANALYTICS_SECRET", ""),
            now=now or datetime.now(timezone.utc),
        )
    except Exception:
        return


def export_aggregate(db_path: str | Path | None = None) -> dict:
    path = Path(db_path) if db_path else _default_db()
    with sqlite3.connect(path) as connection:
        _schema(connection)
        days: dict[tuple[str, str], dict] = {}
        for bot, day, event, success, count, duration_sum, duration_count in connection.execute(
            "SELECT bot, date, event, success, count, duration_sum_ms, duration_count FROM daily"
        ):
            bucket = days.setdefault((bot, day), {
                "date": day,
                "requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "duration_ms_sum": 0,
                "duration_count": 0,
                "commands": {},
            })
            count = int(count)
            bucket["requests"] += count
            if int(success) == 1:
                bucket["successful_requests"] += count
            else:
                bucket["failed_requests"] += count
            bucket["duration_ms_sum"] += int(duration_sum)
            bucket["duration_count"] += int(duration_count)
            bucket["commands"][event] = bucket["commands"].get(event, 0) + count
        for bot, day, users in connection.execute(
            "SELECT bot, period, COUNT(*) FROM users WHERE granularity = 'day' GROUP BY bot, period"
        ):
            bucket = days.setdefault((bot, day), {
                "date": day,
                "requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "duration_ms_sum": 0,
                "duration_count": 0,
                "commands": {},
            })
            bucket["unique_users"] = int(users)
        months: dict[str, list] = {}
        for bot, month, users in connection.execute(
            "SELECT bot, period, COUNT(*) FROM users WHERE granularity = 'month' GROUP BY bot, period"
        ):
            months.setdefault(bot, []).append({"month": month, "unique_users": int(users)})
    bots = []
    names = sorted(set(bot for bot, _day in days) | set(months))
    for name in names:
        day_rows = [days[key] for key in sorted(days) if key[0] == name]
        bots.append({"bot": name, "days": day_rows, "months": months.get(name, [])})
    return {"bots": bots}


def _record(*, bot, event, success, duration_ms, user_id, event_id, db_path: Path, secret: str, now: datetime) -> None:
    if not _EVENT.fullmatch(bot) or not _EVENT.fullmatch(event):
        return
    if duration_ms is not None and float(duration_ms) < 0:
        return
    moment = now.astimezone(timezone.utc)
    day = moment.date().isoformat()
    month = day[:7]
    duration = 0 if duration_ms is None else int(duration_ms)
    duration_count = 0 if duration_ms is None else 1
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        _schema(connection)
        if event_id:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO events (event_id, created_on) VALUES (?, ?)",
                (event_id, day),
            )
            if inserted.rowcount == 0:
                return
        connection.execute(
            """
            INSERT INTO daily (bot, date, event, success, count, duration_sum_ms, duration_count)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT (bot, date, event, success) DO UPDATE SET
                count = count + 1,
                duration_sum_ms = duration_sum_ms + excluded.duration_sum_ms,
                duration_count = duration_count + excluded.duration_count
            """,
            (bot, day, event, 1 if success else 0, duration, duration_count),
        )
        if user_id and secret:
            digest = _hash(secret, bot, user_id)
            connection.execute(
                "INSERT OR IGNORE INTO users (bot, period, granularity, user_hash) VALUES (?, ?, 'day', ?)",
                (bot, day, digest),
            )
            connection.execute(
                "INSERT OR IGNORE INTO users (bot, period, granularity, user_hash) VALUES (?, ?, 'month', ?)",
                (bot, month, digest),
            )
        _purge(connection, moment.date())
        connection.commit()


def _hash(secret: str, bot: str, user_id: str) -> str:
    return hmac.new(secret.encode(), f"{bot}:{user_id}".encode(), hashlib.sha256).hexdigest()[:32]


def _purge(connection: sqlite3.Connection, today: date) -> None:
    day_cutoff = (today - timedelta(days=DAY_RETENTION)).isoformat()
    month_cutoff = (today - timedelta(days=MONTH_RETENTION)).strftime("%Y-%m")
    connection.execute("DELETE FROM users WHERE granularity = 'day' AND period < ?", (day_cutoff,))
    connection.execute("DELETE FROM users WHERE granularity = 'month' AND period < ?", (month_cutoff,))
    connection.execute("DELETE FROM events WHERE created_on < ?", (day_cutoff,))
    connection.execute("DELETE FROM daily WHERE date < ?", (day_cutoff,))


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            created_on TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily (
            bot TEXT NOT NULL,
            date TEXT NOT NULL,
            event TEXT NOT NULL,
            success INTEGER NOT NULL,
            count INTEGER NOT NULL,
            duration_sum_ms INTEGER NOT NULL,
            duration_count INTEGER NOT NULL,
            PRIMARY KEY (bot, date, event, success)
        );
        CREATE TABLE IF NOT EXISTS users (
            bot TEXT NOT NULL,
            period TEXT NOT NULL,
            granularity TEXT NOT NULL,
            user_hash TEXT NOT NULL,
            PRIMARY KEY (bot, period, granularity, user_hash)
        );
        """
    )


def _default_db() -> Path:
    return Path(os.environ.get("ANALYTICS_DB", "data/telemetry/analytics.sqlite"))
