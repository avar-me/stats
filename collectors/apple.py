"""App Store Connect Analytics Reports.

Daily collection downloads existing ONGOING instances. It does not create report
requests: the first request needs an Admin key and is a separate explicit command.
A newer processingDate replaces rows for the same Date. Updates are not counted
as downloads.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import re

import jwt

from collectors.base import CollectResult, Context, Entity, Source, SourceError, SourceNotConfigured
from core.model import Observation, stamp
from core.redact import redact
from core.secrets import load_pem, required

API = "https://api.appstoreconnect.apple.com"
DOWNLOAD_TYPES = {
    "first-time download": "first_time",
    "redownload": "redownload",
    "manual update": "update",
    "auto-update": "update",
    "restore": "restore",
}
_MD5 = re.compile(r"^[0-9a-f]{32}$")


class AppleSource(Source):
    id = "apple"
    title = "App Store"
    hint = (
        "Включите sources.apple.enabled и задайте APPLE_KEY_ID, APPLE_ISSUER_ID, APPLE_PRIVATE_KEY, APPLE_APP_ID. "
        "Один раз создайте ONGOING-запрос ключом Admin: python scripts/apple_request.py --confirm."
    )

    def entities(self, block: dict) -> list[Entity]:
        app_id = str(block.get("app_id") or "6782280983")
        return [Entity(app_id, block.get("title") or "iOS-приложение", block.get("link") or "https://ios.avar.me")]

    def collect(self, ctx: Context) -> CollectResult:
        secrets = required(ctx.env, "APPLE_KEY_ID", "APPLE_ISSUER_ID", "APPLE_PRIVATE_KEY")
        app_id = str(ctx.env.get("APPLE_APP_ID") or ctx.config.get("app_id") or "").strip()
        if not app_id:
            raise SourceNotConfigured("Нужен APPLE_APP_ID.")
        private_key = load_pem(secrets["APPLE_PRIVATE_KEY"])
        token = apple_token(secrets["APPLE_KEY_ID"], secrets["APPLE_ISSUER_ID"], private_key, ctx.now)
        requests = _get_all(ctx.client, token, f"/v1/apps/{app_id}/analyticsReportRequests?filter[accessType]=ONGOING")
        active = [item for item in requests if not (item.get("attributes") or {}).get("stoppedDueToInactivity")]
        if not active:
            if requests:
                raise SourceError(
                    "ONGOING-запрос Apple остановлен из-за неактивности. "
                    "Создайте новый ключом с ролью Admin: python scripts/apple_request.py --confirm"
                )
            raise SourceError(
                "Нет ONGOING-запроса аналитики. Создайте его один раз ключом Admin: "
                "python scripts/apple_request.py --confirm. Первые отчёты появляются через 1–2 дня."
            )
        request_id = active[0]["id"]
        reports = _get_all(
            ctx.client,
            token,
            f"/v1/analyticsReportRequests/{request_id}/reports?filter[category]=COMMERCE",
        )
        report = next((item for item in reports if str((item.get("attributes") or {}).get("name", "")).casefold() == "app downloads standard"), None)
        if report is None:
            names = ", ".join(str((item.get("attributes") or {}).get("name", "")) for item in reports) or "пусто"
            raise SourceError(f"Отчёт App Downloads Standard не найден. Доступны: {names}")
        instances = _get_all(
            ctx.client,
            token,
            f"/v1/analyticsReports/{report['id']}/instances?filter[granularity]=DAILY&limit=200",
        )
        result = CollectResult()
        if not instances:
            result.warnings.append("Экземпляров ежедневного отчёта ещё нет. Apple формирует первые файлы 1–2 дня.")
            return result
        downloaded = []
        collected_at = stamp(ctx.now)
        for instance in instances:
            processing_date = str((instance.get("attributes") or {}).get("processingDate") or "")
            if not processing_date:
                continue
            segments = _get_all(ctx.client, token, f"/v1/analyticsReportInstances/{instance['id']}/segments")
            rows = []
            for segment in segments:
                attributes = segment.get("attributes") or {}
                url = attributes.get("url")
                if not url:
                    continue
                response = ctx.client.request("GET", url, timeout=60)
                warning = verify_segment(response.body, attributes)
                if warning:
                    result.warnings.append(warning)
                rows.extend(parse_segment(response.body))
            downloaded.append({"processing_date": processing_date, "rows": rows})
        chosen = select_latest_rows(downloaded)
        for day, (processing_date, rows) in sorted(chosen.items()):
            result.observations.extend(rows_to_observations(
                rows,
                entity=app_id,
                processing_date=processing_date,
                collected_at=collected_at,
                day=day,
            ))
        return result


def apple_token(key_id: str, issuer: str, private_key: str, now) -> str:
    issued = int(now.timestamp())
    token = jwt.encode(
        {"iss": issuer, "iat": issued, "exp": issued + 15 * 60, "aud": "appstoreconnect-v1"},
        private_key,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"},
    )
    if isinstance(token, bytes):
        return token.decode()
    return token


def select_latest_rows(instances: list[dict]) -> dict[str, tuple[str, list]]:
    """A later processingDate replaces every Date it contains. Rows are not added together."""
    chosen: dict[str, tuple[str, list]] = {}
    for instance in sorted(instances, key=lambda item: item["processing_date"]):
        by_date: dict[str, list] = {}
        for row in instance["rows"]:
            day = _column(row, "date")
            if day:
                by_date.setdefault(day, []).append(row)
        for day, rows in by_date.items():
            current = chosen.get(day)
            if current is None or instance["processing_date"] >= current[0]:
                chosen[day] = (instance["processing_date"], rows)
    return chosen


def rows_to_observations(rows: list[dict], *, entity: str, processing_date: str, collected_at: str, day: str) -> list[Observation]:
    first_time = 0.0
    redownload = 0.0
    saw_first = False
    saw_redownload = False
    by_country: dict[str, float] = {}
    by_device: dict[str, float] = {}
    saw_country = False
    saw_device = False
    for row in rows:
        kind = DOWNLOAD_TYPES.get(_column(row, "download type").casefold())
        raw_count = _column(row, "counts")
        if kind is None or raw_count == "":
            continue
        count = float(raw_count)
        if kind == "first_time":
            first_time += count
            saw_first = True
            territory = _column(row, "territory")
            device = _column(row, "device")
            if territory:
                saw_country = True
                by_country[territory] = by_country.get(territory, 0.0) + count
            if device:
                saw_device = True
                by_device[device] = by_device.get(device, 0.0) + count
        elif kind == "redownload":
            redownload += count
            saw_redownload = True
    status = "delayed" if _age_days(processing_date, day) < 2 else "confirmed"
    observations = []
    if saw_first:
        observations.append(_download("first_time_downloads", entity, day, first_time, status, processing_date, collected_at))
    if saw_redownload:
        observations.append(_download("redownloads", entity, day, redownload, status, processing_date, collected_at))
    if saw_first or saw_redownload:
        observations.append(_download(
            "total_downloads", entity, day, first_time + redownload, status, processing_date, collected_at,
        ))
    if saw_country:
        for country, value in sorted(by_country.items()):
            observations.append(_download(
                "first_time_downloads", entity, day, value, status, processing_date, collected_at, {"country": country},
            ))
    if saw_device:
        for device, value in sorted(by_device.items()):
            observations.append(_download(
                "first_time_downloads", entity, day, value, status, processing_date, collected_at, {"device": device},
            ))
    return observations


def parse_segment(body: bytes) -> list[dict]:
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    text = body.decode("utf-8-sig")
    if not text.strip():
        return []
    header = text.splitlines()[0]
    delimiter = "\t" if "\t" in header else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def verify_segment(body: bytes, attributes: dict) -> str | None:
    size = attributes.get("sizeInBytes")
    if size is not None and int(size) != len(body):
        raise SourceError("Сегмент отчёта Apple не совпал по размеру")
    checksum = str(attributes.get("checksum") or "").lower()
    if checksum and _MD5.fullmatch(checksum):
        digest = hashlib.md5(body).hexdigest()
        if digest != checksum:
            raise SourceError("Контрольная сумма сегмента Apple не совпала")
    return None


def _download(metric, entity, day, value, status, processing_date, collected_at, dimensions=None) -> Observation:
    return Observation(
        source="apple",
        entity=entity,
        metric=metric,
        date=day,
        value=value,
        unit="downloads",
        aggregation="daily",
        collected_at=collected_at,
        status=status,
        dimensions=dimensions or {},
        revision=processing_date,
    )


def _get_all(client, token: str, path: str) -> list:
    items = []
    url = path if path.startswith("https://") else API + path
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    while url:
        response = client.request("GET", url, headers=headers, timeout=40)
        payload = response.json()
        if not isinstance(payload, dict):
            raise SourceError("App Store Connect вернул не объект")
        items.extend(payload.get("data") or [])
        url = (payload.get("links") or {}).get("next")
    return items


def _column(row: dict, name: str) -> str:
    for key, value in row.items():
        if str(key).strip().casefold() == name:
            return str(value or "").strip()
    return ""


def _age_days(processing_date: str, day: str) -> int:
    from datetime import date
    return (date.fromisoformat(processing_date) - date.fromisoformat(day)).days


def create_ongoing_request(client, token: str, app_id: str) -> str:
    body = json_body({
        "data": {
            "type": "analyticsReportRequests",
            "attributes": {"accessType": "ONGOING"},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
        }
    })
    response = client.request(
        "POST",
        API + "/v1/analyticsReportRequests",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
        body=body,
        timeout=40,
    )
    payload = response.json()
    return payload["data"]["id"]


def json_body(payload: dict) -> bytes:
    import json
    return json.dumps(payload).encode()
