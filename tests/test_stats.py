from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from collectors.apple import apple_token, parse_segment, rows_to_observations, select_latest_rows
from collectors.base import Entity, Source, SourceError
from collectors.cloudflare import parse_http_zone, parse_rum_account
from collectors.google_play import decode_report, parse_install_report
from collectors.registry import SOURCES
from collectors.telegram_bots import parse_telemetry
from collectors.telegram_channels import TelegramChannelsSource
from collectors.telegram_stickers import TelegramStickersSource
from core.aggregate import build_public
from core.catalog import INSTALLS_UNAVAILABLE
from core.config import load_config
from core.http import FakeClient
from core.model import Observation
from core.privacy import assert_public_safe
from core.runner import publish, run_sources
from core.store import HistoryStore
from integrations.telegram_bot_analytics import export_aggregate, track_event

NOW = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def observation(**kwargs) -> Observation:
    payload = {
        "source": "telegram_channels",
        "entity": "avarlangme",
        "metric": "subscribers",
        "date": "2026-11-16",
        "value": 10,
        "unit": "subscribers",
        "aggregation": "snapshot",
        "collected_at": "2026-11-16T03:00:00Z",
        "status": "confirmed",
        "revision": "2026-11-16T03:00:00Z",
    }
    payload.update(kwargs)
    return Observation(**payload)


def test_missing_value_is_not_zero_and_forbidden_dimensions_are_rejected():
    point = observation(value=None, status="unavailable")
    assert point.value is None
    with pytest.raises(ValueError):
        observation(dimensions={"user_id": "1"})


def test_store_keeps_newer_revision_and_does_not_erase_with_null(tmp_path):
    store = HistoryStore(tmp_path)
    store.merge("apple", [observation(source="apple", entity="1", metric="first_time_downloads", value=10, unit="downloads", aggregation="daily", revision="2026-11-05")])
    store.merge("apple", [observation(source="apple", entity="1", metric="first_time_downloads", value=99, unit="downloads", aggregation="daily", revision="2026-11-01")])
    store.merge("apple", [observation(source="apple", entity="1", metric="first_time_downloads", value=None, status="unavailable", unit="downloads", aggregation="daily", revision="2026-11-10")])
    stored = store.observations("apple")
    assert stored[0]["value"] == 10
    store.merge("apple", [observation(source="apple", entity="1", metric="first_time_downloads", value=12, unit="downloads", aggregation="daily", revision="2026-11-06")])
    assert store.observations("apple")[0]["value"] == 12
    assert len(store.observations("apple")) == 1


def test_windows_do_not_invent_missing_days_and_deltas_need_a_real_prior_point(tmp_path):
    store = HistoryStore(tmp_path)
    points = [
        observation(source="cloudflare", entity="avar.me", metric="page_views", date="2026-11-13", value=1, unit="views", aggregation="daily"),
        observation(source="cloudflare", entity="avar.me", metric="page_views", date="2026-11-15", value=1, unit="views", aggregation="daily"),
        observation(source="cloudflare", entity="avar.me", metric="page_views", date="2026-11-16", value=1, unit="views", aggregation="daily"),
        observation(
            source="cloudflare", entity="avar.me", metric="page_views", date="2026-11-16", value=50, unit="views",
            aggregation="period", dimensions={"path": "/?q=secret"},
        ),
    ]
    store.merge("cloudflare", points)
    summary, _history = build_public(store, {"sources": {"cloudflare": {"enabled": True, "sites": [{"hostname": "avar.me", "enabled": True}]}}}, [_source("cloudflare", [Entity("avar.me", "avar.me")])], NOW)
    metric = summary["sources"][0]["entities"][0]["metrics"][0]
    assert metric["window_7d"]["sum"] == 3
    assert metric["window_7d"]["days_present"] == 3
    assert metric["window_7d"]["days_expected"] == 7
    assert metric["delta_7d"] is None


def test_snapshot_delta_uses_an_existing_point_and_partial_channels_do_not_invent_a_total(tmp_path):
    store = HistoryStore(tmp_path)
    rows = [
        observation(entity="avarlangme", date="2026-11-01", value=100),
        observation(entity="avarlangme", date="2026-11-09", value=110),
        observation(entity="avarlangme", date="2026-11-16", value=120),
        observation(entity="avar_kino", date="2026-11-16", value=40),
    ]
    store.merge("telegram_channels", rows)
    block = {"enabled": True, "channels": [
        {"username": "avarlangme", "enabled": True},
        {"username": "avar_kino", "enabled": True},
    ]}
    summary, _history = build_public(
        store,
        {"sources": {"telegram_channels": block}},
        [_source("telegram_channels", TelegramChannelsSource().entities(block))],
        NOW,
    )
    card = summary["cards"][0]
    assert card["value"] == 160
    assert card["partial"] is False
    assert card["delta_7d"] is None
    entity = summary["sources"][0]["entities"][0]
    assert entity["metrics"][0]["delta_7d"] == 10
    assert entity["metrics"][0]["delta_7d_from"] == "2026-11-09"
    units = {item["unit"] for item in summary["cards"]}
    assert units == {"subscribers"}
    assert "unique_users" not in {item["id"] for item in summary["cards"]}


def test_apple_latest_instance_replaces_a_date_and_updates_are_not_downloads():
    older = parse_segment(_tsv(
        "Date\tDownload Type\tCounts\tTerritory\tDevice\n"
        "2026-11-01\tFirst-time Download\t10\tRU\tiPhone\n"
        "2026-11-01\tAuto-update\t100\tRU\tiPhone\n"
    ))
    newer = parse_segment(_tsv(
        "Date\tDownload Type\tCounts\tTerritory\tDevice\n"
        "2026-11-01\tFirst-time Download\t4\tRU\tiPhone\n"
        "2026-11-01\tFirst-time Download\t1\tUS\tiPad\n"
        "2026-11-01\tRedownload\t2\tRU\tiPhone\n"
        "2026-11-01\tManual update\t80\tRU\tiPhone\n"
    ))
    chosen = select_latest_rows([
        {"processing_date": "2026-11-02", "rows": older},
        {"processing_date": "2026-11-05", "rows": newer},
    ])
    observations = rows_to_observations(
        chosen["2026-11-01"][1], entity="6782280983", processing_date="2026-11-05",
        collected_at="2026-11-16T03:00:00Z", day="2026-11-01",
    )
    by_key = {(item.metric, tuple(item.dimensions.items())): item.value for item in observations}
    assert by_key[("first_time_downloads", ())] == 5
    assert by_key[("total_downloads", ())] == 7
    assert by_key[("first_time_downloads", (("country", "RU"),))] == 4
    assert by_key[("first_time_downloads", (("device", "iPad"),))] == 1
    assert all(item.status == "confirmed" for item in observations)
    delayed = rows_to_observations(
        newer, entity="6782280983", processing_date="2026-11-02",
        collected_at="2026-11-16T03:00:00Z", day="2026-11-01",
    )
    assert delayed[0].status == "delayed"


def test_apple_token_expires_within_twenty_minutes():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    token = apple_token("KEYID", "issuer-id", pem, NOW)
    claims = jwt.decode(
        token,
        key.public_key(),
        algorithms=["ES256"],
        audience="appstoreconnect-v1",
        options={"verify_exp": False},
    )
    assert claims["iss"] == "issuer-id"
    assert claims["exp"] - claims["iat"] == 15 * 60


def test_cloudflare_keeps_visits_page_views_and_http_requests_apart():
    account = {
        "daily": [
            {"count": 10, "sum": {"visits": 4}, "avg": {"sampleInterval": 1}, "dimensions": {"date": "2026-11-15", "requestHost": "avar.me"}},
            {"count": 99, "sum": {"visits": 70}, "avg": {"sampleInterval": 1}, "dimensions": {"date": "2026-11-15", "requestHost": "other.example"}},
            {"count": 0, "sum": {}, "avg": {"sampleInterval": 1}, "dimensions": {"date": "2026-11-14", "requestHost": "avar.me"}},
            {"count": 3, "sum": {"visits": 1}, "avg": {"sampleInterval": 8}, "dimensions": {"date": "2026-11-16", "requestHost": "avar.me"}},
        ],
        "countries": [
            {"count": 7, "dimensions": {"date": "2026-11-15", "countryName": "RU", "requestHost": "avar.me"}},
            {"count": 50, "dimensions": {"date": "2026-11-15", "countryName": "US", "requestHost": "other.example"}},
        ],
        "pages": [{"count": 6, "dimensions": {"requestHost": "avar.me", "requestPath": "/search?q=secret#part"}}],
        "referrers": [{"count": 2, "dimensions": {"requestHost": "avar.me", "refererHost": "t.me"}}],
    }
    observations, _warnings = parse_rum_account(account, entity="avar.me", collected_at="2026-11-16T03:00:00Z", today="2026-11-16")
    daily = {(item.metric, item.date, tuple(item.dimensions.items())): item for item in observations if item.aggregation == "daily" and not item.dimensions}
    assert daily[("page_views", "2026-11-15", ())].value == 10
    assert daily[("visits", "2026-11-15", ())].value == 4
    assert daily[("page_views", "2026-11-14", ())].value == 0
    assert ("visits", "2026-11-14", ()) not in daily
    assert daily[("page_views", "2026-11-16", ())].status == "estimated"
    countries = [item for item in observations if item.dimensions.get("country")]
    assert [item.dimensions["country"] for item in countries] == ["RU"]
    path = next(item for item in observations if item.aggregation == "period" and "path" in item.dimensions)
    assert path.dimensions["path"] == "/search"
    http = parse_http_zone(
        {"httpRequests1dGroups": [{"dimensions": {"date": "2026-11-15"}, "sum": {"requests": 80, "pageViews": 80}, "uniq": {"uniques": 11}}]},
        entity="avar.me", collected_at="2026-11-16T03:00:00Z", today="2026-11-16",
    )
    assert {item.metric for item in http} == {"http_requests", "http_unique_ips"}
    assert all(item.unit != "views" for item in http)


def test_google_play_empty_cell_is_not_zero_and_countries_do_not_increase_the_total():
    text = decode_report((
        "Date,Package Name,Daily User Installs,Current User Installs,Daily User Uninstalls,Daily Device Installs\n"
        "2026-11-01,me.avar.dictionary,,8,1,3\n"
        "2026-11-12,me.avar.dictionary,0,9,0,4\n"
        "2026-11-14,me.avar.dictionary,4,10,2,5\n"
    ).encode("utf-16"))
    totals = parse_install_report(text, package="me.avar.dictionary", collected_at="2026-11-16T03:00:00Z", today=NOW.date(), estimated=False)
    first = {(item.date, item.metric): item for item in totals if item.metric == "first_time_installs"}
    assert ("2026-11-01", "first_time_installs") not in first
    assert first[("2026-11-12", "first_time_installs")].value == 0
    assert first[("2026-11-14", "first_time_installs")].status == "delayed"
    assert first[("2026-11-12", "first_time_installs")].status == "confirmed"
    countries = parse_install_report(
        "Date,Package Name,Country,Daily User Installs\n2026-11-14,me.avar.dictionary,RU,3\n2026-11-14,me.avar.dictionary,US,1\n",
        package="me.avar.dictionary", collected_at="2026-11-16T03:00:00Z", today=NOW.date(), estimated=False, countries_only=True,
    )
    assert {item.dimensions["country"] for item in countries} == {"RU", "US"}
    assert sum(item.value for item in totals if item.metric == "first_time_installs" and item.date == "2026-11-14") == 4


def test_sticker_collector_does_not_invent_installs_and_isolates_a_channel_error():
    stickers = FakeClient([
        ("GET", "getStickerSet", 200, {"ok": True, "result": {
            "title": "Хӏарпик",
            "sticker_type": "regular",
            "stickers": [{"emoji": "📖"}, {"emoji": "📖"}, {"emoji": "☀"}],
        }}),
    ])
    result = TelegramStickersSource().collect(_context(
        {"packs": [{"name": "AvarMe", "enabled": True}]},
        {"TELEGRAM_BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"},
        stickers,
    ))
    assert {item.metric for item in result.observations} == {"sticker_count"}
    assert result.observations[0].value == 3
    assert result.entity_info["AvarMe"]["installs_note"] == INSTALLS_UNAVAILABLE
    channels = FakeClient([
        ("GET", "chat_id=@avarlangme", 200, {"ok": True, "result": 42}),
    ])
    channel_result = TelegramChannelsSource().collect(_context(
        {"channels": [
            {"username": "avarlangme", "enabled": True},
            {"username": "missing_channel", "enabled": True},
        ]},
        {"TELEGRAM_BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"},
        channels,
    ))
    assert [item.entity for item in channel_result.observations] == ["avarlangme"]
    assert "123456789:" not in channel_result.entity_errors["missing_channel"]


def test_telemetry_ignores_private_fields_and_hashes_are_stable_across_days(tmp_path):
    payload = {
        "bots": [{
            "bot": "avar_me_bot",
            "user_id": "should-not-survive",
            "days": [{
                "date": "2026-11-16",
                "requests": 3,
                "unique_users": 2,
                "user_id": "99",
                "query": "лъим",
                "commands": {"dictionary_lookup": 3, "what is the word": 9},
            }],
            "months": [{"month": "2026-11", "unique_users": 2}],
        }, {
            "bot": "other_bot",
            "days": [{"date": "2026-11-16", "requests": 100}],
        }]
    }
    observations = parse_telemetry(payload, collected_at="2026-11-16T03:00:00Z", allowed_bots={"avar_me_bot"})
    dumped = json.dumps([item.to_dict() for item in observations], ensure_ascii=False)
    assert "should-not-survive" not in dumped
    assert "лъим" not in dumped
    assert "other_bot" not in dumped
    assert any(item.metric == "command_requests" and item.dimensions["command"] == "dictionary_lookup" for item in observations)
    assert not any(item.dimensions.get("command") == "what is the word" for item in observations)

    db = tmp_path / "analytics.sqlite"
    secret = "test-secret-value"
    first = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
    second = first + timedelta(days=1)
    track_event(bot="avar_me_bot", event="dictionary_lookup", success=True, duration_ms=120, user_id="user-RAW-998877", event_id="1", db_path=db, secret=secret, now=first)
    track_event(bot="avar_me_bot", event="dictionary_lookup", success=False, duration_ms=10, user_id="user-RAW-998877", event_id="1", db_path=db, secret=secret, now=second)
    track_event(bot="avar_me_bot", event="dictionary_lookup", success=True, duration_ms=30, user_id="user-RAW-998877", event_id="2", db_path=db, secret=secret, now=second)
    track_event(bot="bad name", event="dictionary_lookup", success=True, db_path=db, secret=secret, now=second)
    track_event(bot="avar_me_bot", event="dictionary_lookup", success=True, duration_ms=-1, db_path=db, secret=secret, now=second)
    track_event(bot="avar_me_bot", event="dictionary_lookup", success=True, db_path=Path("/dev/null/nope"), secret=secret, now=second)
    exported = export_aggregate(db)
    assert_public_safe(exported)
    blob = db.read_bytes()
    assert b"user-RAW-998877" not in blob
    november = exported["bots"][0]["months"][0]
    assert november["unique_users"] == 1
    days = {row["date"]: row for row in exported["bots"][0]["days"]}
    assert days["2026-11-15"]["requests"] == 1
    assert days["2026-11-16"]["requests"] == 1
    assert days["2026-11-16"]["unique_users"] == 1
    assert days["2026-11-15"]["unique_users"] == 1


def test_one_source_failing_does_not_reset_the_other(tmp_path):
    class Healthy(Source):
        id = "telegram_channels"
        title = "Telegram-каналы"
        hint = ""

        def entities(self, block):
            return [Entity("avarlangme", "Канал")]

        def collect(self, ctx):
            from collectors.base import CollectResult
            return CollectResult(observations=[observation()])

    class Broken(Source):
        id = "cloudflare"
        title = "Сайты"
        hint = ""

        def entities(self, block):
            return [Entity("avar.me", "avar.me")]

        def collect(self, ctx):
            raise SourceError("token 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd")

    config = {"sources": {"telegram_channels": {"enabled": True}, "cloudflare": {"enabled": True}}}
    reports = run_sources(config, root=tmp_path, env={}, now=NOW, sources=[Healthy(), Broken()])
    assert {item.source: item.status for item in reports}["telegram_channels"] == "ok"
    assert {item.source: item.status for item in reports}["cloudflare"] == "error"
    assert HistoryStore(tmp_path).observations("telegram_channels")[0]["value"] == 10
    error = HistoryStore(tmp_path).load("cloudflare")["meta"]["last_error"]
    assert "123456789:" not in error
    summary, history = publish(config, root=tmp_path, now=NOW, sources=[Healthy(), Broken()])
    assert_public_safe(summary)
    assert_public_safe(history)
    assert "123456789:" not in json.dumps(summary)


def test_disabled_source_keeps_history_and_real_config_starts_without_credentials(tmp_path):
    store = HistoryStore(tmp_path)
    store.merge("apple", [observation(source="apple", entity="6782280983", metric="first_time_downloads", value=4, unit="downloads", aggregation="daily")])
    store.record_run("apple", state="ok", attempted_at="2026-11-01T03:00:00Z", records=1, success=True)
    config = load_config(ROOT / "config.yaml")
    reports = run_sources(config, root=tmp_path, env={}, now=NOW, sources=[item() for item in SOURCES])
    assert next(item.status for item in reports if item.source == "apple") == "disabled"
    assert store.observations("apple")[0]["value"] == 4
    summary, _history = publish(config, root=tmp_path, now=NOW)
    statuses = {item["id"]: item["status"] for item in summary["sources"]}
    assert statuses["apple"] == "disabled"
    assert statuses["google_play"] == "disabled"
    assert statuses["telegram_bots"] == "disabled"
    assert statuses["telegram_channels"] == "not_configured"
    assert statuses["cloudflare"] == "not_configured"
    assert INSTALLS_UNAVAILABLE in json.dumps(summary, ensure_ascii=False)
    assert summary["preview"] is False


def test_source_modules_do_not_import_each_other():
    for path in (ROOT / "collectors").glob("*.py"):
        if path.name in {"registry.py", "__init__.py"}:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("from collectors.") or stripped.startswith("import collectors."):
                assert stripped.startswith("from collectors.base") or stripped.startswith("import collectors.base")
    assert [item.id for item in (source() for source in SOURCES)] == [
        "telegram_channels", "telegram_stickers", "cloudflare", "apple", "google_play", "telegram_bots",
    ]


def _context(config, env, client):
    from collectors.base import Context
    return Context(config=config, env=env, now=NOW, client=client, root=ROOT)


def _source(source_id, entities):
    class Adapter(Source):
        id = source_id
        title = source_id
        hint = ""

        def entities(self, block):
            return entities

    return Adapter()


def _tsv(text: str) -> bytes:
    import gzip
    return gzip.compress(text.encode())


def test_card_window_counts_days_any_site_reported_and_skips_sites_without_recent_data(tmp_path):
    store = HistoryStore(tmp_path)
    store.merge("cloudflare", [
        observation(source="cloudflare", entity="avar.me", metric="page_views", date="2026-11-16", value=5, unit="views", aggregation="daily"),
        observation(source="cloudflare", entity="avar.me", metric="page_views", date="2026-11-15", value=5, unit="views", aggregation="daily"),
        observation(source="cloudflare", entity="index.avar.me", metric="page_views", date="2026-10-22", value=7, unit="views", aggregation="daily"),
    ])
    entities = [Entity("avar.me", "avar.me"), Entity("index.avar.me", "index.avar.me")]
    summary, _history = build_public(
        store, {"sources": {"cloudflare": {"enabled": True}}}, [_source("cloudflare", entities)], NOW,
    )
    card = next(item for item in summary["cards"] if item["id"] == "cloudflare.page_views")
    # index.avar.me stopped on 2026-10-22: its old views must not appear as "last 7 days".
    assert card["value"] == 5  # newest day only: index.avar.me is not added to today
    assert card["window_7d"]["sum"] == 10
    assert card["window_7d"]["days_present"] == 2
    assert card["window_30d"]["sum"] == 17
    assert card["window_30d"]["days_present"] == 3
    assert "_dates" not in json.dumps(summary)


def test_source_and_entity_notes_survive_public_filtering(tmp_path):
    store = HistoryStore(tmp_path)
    store.record_run("telegram_channels", state="error", attempted_at="2026-11-16T03:00:00Z", records=0,
                     error="Нет доступа к каналу", entity_errors={"avarlangme": "chat not found"})
    block = {"enabled": True, "channels": [{"username": "avarlangme", "enabled": True}]}
    summary, _history = build_public(store, {"sources": {"telegram_channels": block}},
                                     [_source("telegram_channels", TelegramChannelsSource().entities(block))], NOW)
    source = summary["sources"][0]
    assert source["note"] == "Нет доступа к каналу"
    assert source["entities"][0]["note"] == "chat not found"
    assert "message" not in source
