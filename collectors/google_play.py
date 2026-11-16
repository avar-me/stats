"""Google Play install statistics from the official Cloud Storage bulk reports.

The Play Developer Reporting API covers vitals (crashes, ANRs) and does not
provide installs, so this module reads the monthly CSV exports only:

    gs://<bucket>/stats/installs/installs_<package>_yyyyMM_overview.csv
    gs://<bucket>/stats/installs/installs_<package>_yyyyMM_country.csv

Country rows are a breakdown. They are not added on top of the overview total.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from urllib.parse import quote

import jwt

from collectors.base import CollectResult, Context, Entity, Source, SourceError, SourceNotConfigured
from core.model import Observation, stamp
from core.redact import redact
from core.secrets import load_service_account, required

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"
COLUMNS = {
    "daily user installs": ("first_time_installs", "users", "daily"),
    "current user installs": ("installed_audience", "users", "daily"),
    "daily user uninstalls": ("uninstalls", "users", "daily"),
    "daily device installs": ("device_installs", "devices", "daily"),
}


class GooglePlaySource(Source):
    id = "google_play"
    title = "Google Play"
    hint = (
        "Включите sources.google_play.enabled. Нужны GOOGLE_PLAY_CREDENTIALS и GOOGLE_PLAY_BUCKET. "
        "Play Developer Reporting API установки не отдаёт: модуль читает ежемесячные CSV из Cloud Storage."
    )

    def entities(self, block: dict) -> list[Entity]:
        package = str(block.get("package") or "me.avar.dictionary")
        return [Entity(package, block.get("title") or "Android-приложение", block.get("link") or "https://android.avar.me")]

    def collect(self, ctx: Context) -> CollectResult:
        secrets = required(ctx.env, "GOOGLE_PLAY_CREDENTIALS")
        bucket = (ctx.env.get("GOOGLE_PLAY_BUCKET") or ctx.config.get("bucket") or "").strip()
        if not bucket:
            raise SourceNotConfigured(
                "Нужен GOOGLE_PLAY_BUCKET — URI бакета из Play Console → Download reports → Statistics."
            )
        bucket = bucket.removeprefix("gs://").strip("/")
        package = str(ctx.config.get("package") or "me.avar.dictionary")
        account = load_service_account(secrets["GOOGLE_PLAY_CREDENTIALS"])
        token = google_access_token(ctx.client, account, ctx.now)
        result = CollectResult()
        collected_at = stamp(ctx.now)
        today = ctx.now.date()
        found = False
        for month in _months(today):
            prefix = f"stats/installs/installs_{package}_{month}"
            try:
                names = list_objects(ctx.client, token, bucket, prefix)
            except SourceError as error:
                raise SourceError(redact(str(error))) from error
            overview = f"{prefix}_overview.csv"
            country = f"{prefix}_country.csv"
            if overview in names:
                found = True
                text = _download(ctx.client, token, bucket, overview)
                result.observations.extend(parse_install_report(
                    text, package=package, collected_at=collected_at, today=today, estimated=False,
                ))
            elif country in names:
                found = True
                result.warnings.append(f"{month}: нет обзорного файла, итог оценён суммой стран")
                text = _download(ctx.client, token, bucket, country)
                result.observations.extend(parse_install_report(
                    text, package=package, collected_at=collected_at, today=today, estimated=True,
                ))
                result.observations.extend(parse_install_report(
                    text, package=package, collected_at=collected_at, today=today, estimated=True, countries_only=True,
                ))
            if country in names and overview in names:
                text = _download(ctx.client, token, bucket, country)
                result.observations.extend(parse_install_report(
                    text,
                    package=package,
                    collected_at=collected_at,
                    today=today,
                    estimated=False,
                    countries_only=True,
                ))
        if not found:
            raise SourceError(
                f"В бакете нет stats/installs для {package}. "
                "Проверьте имя бакета и право сервисного аккаунта View app information."
            )
        return result


def google_access_token(client, account: dict, now) -> str:
    issued = int(now.timestamp())
    assertion = jwt.encode(
        {
            "iss": account["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": issued,
            "exp": issued + 3600,
        },
        account["private_key"],
        algorithm="RS256",
    )
    if isinstance(assertion, bytes):
        assertion = assertion.decode()
    body = (
        "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
        f"&assertion={quote(assertion, safe='')}"
    ).encode()
    response = client.request(
        "POST",
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
        timeout=30,
    )
    payload = response.json()
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise SourceError("Google не выдал access_token для чтения отчётов Play")
    return token


def list_objects(client, token: str, bucket: str, prefix: str) -> list[str]:
    url = (
        "https://storage.googleapis.com/storage/v1/b/"
        f"{quote(bucket, safe='')}/o?prefix={quote(prefix, safe='')}"
    )
    response = client.request("GET", url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    payload = response.json()
    return [item["name"] for item in (payload.get("items") or []) if item.get("name")]


def decode_report(body: bytes) -> str:
    if body.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in body[:80]:
        return body.decode("utf-16")
    return body.decode("utf-8-sig")


def parse_install_report(
    text: str,
    *,
    package: str,
    collected_at: str,
    today: date,
    estimated: bool,
    countries_only: bool = False,
) -> list[Observation]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    observations: list[Observation] = []
    totals: dict[tuple, float] = {}
    seen: set[tuple] = set()
    for row in reader:
        normalized = {str(key).strip().casefold(): (value or "").strip() for key, value in row.items() if key}
        row_package = normalized.get("package name")
        if row_package and row_package != package:
            continue
        day = normalized.get("date", "")
        if len(day) != 10:
            continue
        country = normalized.get("country", "")
        if countries_only and not country:
            continue
        if not countries_only and country:
            country = ""
        for column, (metric, unit, aggregation) in COLUMNS.items():
            raw = normalized.get(column, "")
            if raw == "":
                continue
            key = (day, metric, country, unit, aggregation)
            totals[key] = totals.get(key, 0.0) + float(raw)
            seen.add(key)
    for (day, metric, country, unit, aggregation), value in sorted(totals.items()):
        if (day, metric, country, unit, aggregation) not in seen:
            continue
        status = "estimated" if estimated else ("delayed" if _recent(day, today) else "confirmed")
        dimensions = {"country": country} if country else {}
        observations.append(Observation(
            source="google_play",
            entity=package,
            metric=metric,
            date=day,
            value=value,
            unit=unit,
            aggregation=aggregation,
            collected_at=collected_at,
            status=status,
            dimensions=dimensions,
            revision=collected_at,
        ))
    return observations


def _download(client, token: str, bucket: str, name: str) -> str:
    url = (
        "https://storage.googleapis.com/storage/v1/b/"
        f"{quote(bucket, safe='')}/o/{quote(name, safe='')}?alt=media"
    )
    response = client.request("GET", url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    return decode_report(response.body)


def _months(today: date) -> list[str]:
    previous = today.replace(day=1)
    # step back one month
    previous = (previous - date.resolution).replace(day=1)
    return [previous.strftime("%Y%m"), today.strftime("%Y%m")]


def _recent(day: str, today: date) -> bool:
    return (today - date.fromisoformat(day)).days <= 3
