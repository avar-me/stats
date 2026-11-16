"""Cloudflare Web Analytics and, separately, zone HTTP requests.

Web Analytics comes from rumPageloadEventsAdaptiveGroups (browser beacon).
Zone HTTP requests come from httpRequests1dGroups. The two are never added together,
and zone uniques are labeled as IP addresses rather than visitors.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

from collectors.base import CollectResult, Context, Entity, Source, SourceError, SourceNotConfigured
from core.model import Observation, stamp
from core.redact import redact
from core.secrets import required

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
COUNTRY_LIMIT = 2000

RUM_QUERY = """
query ($account: String!, $site: String!, $start: Date!, $end: Date!) {
  viewer {
    accounts(filter: { accountTag: $account }) {
      daily: rumPageloadEventsAdaptiveGroups(
        limit: 500
        filter: { siteTag: $site, bot: 0, date_geq: $start, date_leq: $end }
        orderBy: [date_ASC]
      ) {
        count
        avg { sampleInterval }
        sum { visits }
        dimensions { date requestHost }
      }
      countries: rumPageloadEventsAdaptiveGroups(
        limit: 2000
        filter: { siteTag: $site, bot: 0, date_geq: $start, date_leq: $end }
        orderBy: [date_ASC]
      ) {
        count
        dimensions { date countryName requestHost }
      }
      pages: rumPageloadEventsAdaptiveGroups(
        limit: 20
        filter: { siteTag: $site, bot: 0, date_geq: $start, date_leq: $end }
        orderBy: [count_DESC]
      ) {
        count
        dimensions { requestHost requestPath }
      }
      referrers: rumPageloadEventsAdaptiveGroups(
        limit: 20
        filter: { siteTag: $site, bot: 0, date_geq: $start, date_leq: $end }
        orderBy: [count_DESC]
      ) {
        count
        dimensions { requestHost refererHost }
      }
    }
  }
}
"""

HTTP_QUERY = """
query ($zone: String!, $start: Date!, $end: Date!) {
  viewer {
    zones(filter: { zoneTag: $zone }) {
      httpRequests1dGroups(
        limit: 100
        filter: { date_geq: $start, date_leq: $end }
        orderBy: [date_ASC]
      ) {
        dimensions { date }
        sum { requests }
        uniq { uniques }
      }
    }
  }
}
"""


class CloudflareSource(Source):
    id = "cloudflare"
    title = "Сайты"
    hint = (
        "Секреты CLOUDFLARE_API_TOKEN (Account Analytics Read) и CLOUDFLARE_ACCOUNT_ID. "
        "У каждого сайта свой site_tag из data-cf-beacon. zone_id необязателен и нужен только для HTTP-запросов."
    )

    def entities(self, block: dict) -> list[Entity]:
        entities = []
        for site in block.get("sites") or []:
            if not site.get("enabled", True):
                continue
            host = str(site["hostname"]).strip().lower()
            entities.append(Entity(host, site.get("title") or host, f"https://{host}"))
        return entities

    def collect(self, ctx: Context) -> CollectResult:
        secrets = required(ctx.env, "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")
        sites = [site for site in ctx.config.get("sites") or [] if site.get("enabled", True)]
        tagged = [site for site in sites if str(site.get("site_tag") or "").strip()]
        if not tagged:
            raise SourceNotConfigured(
                "Нужен site_tag Cloudflare Web Analytics для каждого сайта. "
                "Он виден в атрибуте data-cf-beacon и не совпадает с zone id."
            )
        lookback = int(ctx.config.get("lookback_days") or 30)
        end = ctx.now.date()
        start = end - timedelta(days=lookback - 1)
        result = CollectResult()
        collected_at = stamp(ctx.now)
        for site in sites:
            host = str(site["hostname"]).strip().lower()
            site_tag = str(site.get("site_tag") or "").strip()
            if not site_tag:
                result.entity_errors[host] = "Нужен site_tag из атрибута data-cf-beacon."
                continue
            try:
                payload = _graphql(ctx.client, secrets["CLOUDFLARE_API_TOKEN"], RUM_QUERY, {
                    "account": secrets["CLOUDFLARE_ACCOUNT_ID"],
                    "site": site_tag,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                })
                account = _first(payload, "accounts")
                observations, warnings = parse_rum_account(
                    account,
                    entity=host,
                    collected_at=collected_at,
                    today=end.isoformat(),
                )
                result.observations.extend(observations)
                result.warnings.extend(f"{host}: {warning}" for warning in warnings)
            except (SourceError, KeyError, TypeError, ValueError) as error:
                result.entity_errors[host] = redact(str(error))
                continue
            zone_id = str(site.get("zone_id") or "").strip()
            if not zone_id:
                continue
            try:
                http_payload = _graphql(ctx.client, secrets["CLOUDFLARE_API_TOKEN"], HTTP_QUERY, {
                    "zone": zone_id,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                })
                zone = _first(http_payload, "zones")
                result.observations.extend(parse_http_zone(
                    zone,
                    entity=host,
                    collected_at=collected_at,
                    today=end.isoformat(),
                ))
            except (SourceError, KeyError, TypeError, ValueError) as error:
                result.warnings.append(f"{host}: HTTP-аналитика зоны недоступна ({redact(str(error))})")
        if not result.observations and result.entity_errors and not result.warnings:
            details = "; ".join(f"{key}: {value}" for key, value in result.entity_errors.items())
            raise SourceError(details)
        return result


def parse_rum_account(account: dict, *, entity: str, collected_at: str, today: str) -> tuple[list[Observation], list[str]]:
    warnings: list[str] = []
    observations: list[Observation] = []
    daily_rows = _matching(account.get("daily"), entity)
    if any(len(account.get(name) or []) >= COUNTRY_LIMIT for name in ("countries",)):
        warnings.append("срез по странам упёрся в лимит запроса и может быть неполным")
    by_date: dict[str, dict] = defaultdict(lambda: {"views": 0.0, "visits": 0.0, "sampled": False, "views_seen": False, "visits_seen": False})
    for row in daily_rows:
        day = str((row.get("dimensions") or {}).get("date") or "")
        if len(day) != 10:
            continue
        bucket = by_date[day]
        if row.get("count") is not None:
            bucket["views"] += float(row["count"])
            bucket["views_seen"] = True
        visits = (row.get("sum") or {}).get("visits")
        if visits is not None:
            bucket["visits"] += float(visits)
            bucket["visits_seen"] = True
        interval = (row.get("avg") or {}).get("sampleInterval")
        if interval is not None and float(interval) > 1:
            bucket["sampled"] = True
    for day, bucket in sorted(by_date.items()):
        status = _status(day, today, bucket["sampled"])
        if bucket["views_seen"]:
            observations.append(_point("page_views", entity, day, bucket["views"], "views", collected_at, status))
        if bucket["visits_seen"]:
            observations.append(_point("visits", entity, day, bucket["visits"], "visits", collected_at, status))
    country_totals: dict[tuple[str, str], float] = defaultdict(float)
    truncated = len(account.get("countries") or []) >= COUNTRY_LIMIT
    for row in _matching(account.get("countries"), entity):
        if row.get("count") is None:
            continue
        dimensions = row.get("dimensions") or {}
        day = str(dimensions.get("date") or "")
        country = str(dimensions.get("countryName") or "").strip()
        if len(day) != 10 or not country:
            continue
        country_totals[(day, country)] += float(row["count"])
    for (day, country), value in sorted(country_totals.items()):
        observations.append(_point(
            "page_views",
            entity,
            day,
            value,
            "views",
            collected_at,
            "estimated" if truncated else _status(day, today, False),
            {"country": country},
        ))
    end_dates = sorted(by_date)
    end = end_dates[-1] if end_dates else today
    for row in _matching(account.get("pages"), entity):
        if row.get("count") is None:
            continue
        dimensions = row.get("dimensions") or {}
        path = _clean_path(str(dimensions.get("requestPath") or ""))
        observations.append(_point(
            "page_views", entity, end, float(row["count"]), "views", collected_at, "confirmed",
            {"path": path}, "period",
        ))
    for row in _matching(account.get("referrers"), entity):
        if row.get("count") is None:
            continue
        host = str((row.get("dimensions") or {}).get("refererHost") or "").strip()
        if not host:
            host = "(прямой заход)"
        observations.append(_point(
            "page_views", entity, end, float(row["count"]), "views", collected_at, "confirmed",
            {"referrer": host[:180]}, "period",
        ))
    return observations, warnings


def parse_http_zone(zone: dict, *, entity: str, collected_at: str, today: str) -> list[Observation]:
    observations = []
    for row in zone.get("httpRequests1dGroups") or []:
        day = str((row.get("dimensions") or {}).get("date") or "")
        if len(day) != 10:
            continue
        requests = (row.get("sum") or {}).get("requests")
        uniques = (row.get("uniq") or {}).get("uniques")
        status = "delayed" if day >= today else "confirmed"
        if requests is not None:
            observations.append(_point("http_requests", entity, day, float(requests), "requests", collected_at, status))
        if uniques is not None:
            observations.append(_point("http_unique_ips", entity, day, float(uniques), "ips", collected_at, status))
    return observations


def _graphql(client, token: str, query: str, variables: dict) -> dict:
    response = client.request(
        "POST",
        GRAPHQL_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        body=json.dumps({"query": query, "variables": variables}).encode(),
        timeout=40,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise SourceError("Cloudflare вернул не объект")
    errors = payload.get("errors") or []
    if errors:
        message = "; ".join(str(item.get("message", item)) if isinstance(item, dict) else str(item) for item in errors)
        raise SourceError(redact(message)[:500])
    data = payload.get("data") or {}
    viewer = data.get("viewer") or {}
    if not viewer:
        raise SourceError("В ответе Cloudflare нет viewer")
    return viewer


def _first(viewer: dict, key: str) -> dict:
    rows = viewer.get(key) or []
    if not rows:
        raise SourceError(f"Cloudflare не вернул {key}")
    return rows[0]


def _matching(rows, hostname: str) -> list:
    decorated = []
    any_host = False
    for row in rows or []:
        host = str((row.get("dimensions") or {}).get("requestHost") or "").strip().lower()
        if host:
            any_host = True
        decorated.append((row, host))
    if not any_host:
        return [row for row, _host in decorated]
    return [row for row, host in decorated if host == hostname.lower()]


def _status(day: str, today: str, sampled: bool) -> str:
    if sampled:
        return "estimated"
    if day >= today:
        return "delayed"
    return "confirmed"


def _clean_path(path: str) -> str:
    path = path.split("?", 1)[0].split("#", 1)[0].strip()
    return (path or "/")[:180]


def _point(metric, entity, day, value, unit, collected_at, status, dimensions=None, aggregation="daily") -> Observation:
    return Observation(
        source="cloudflare",
        entity=entity,
        metric=metric,
        date=day,
        value=value,
        unit=unit,
        aggregation=aggregation,
        collected_at=collected_at,
        status=status,
        dimensions=dimensions or {},
        revision=collected_at,
    )
