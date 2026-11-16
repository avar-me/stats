"""Metric definitions. The dashboard copy comes from here so labels stay with their meaning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    source: str
    metric: str
    label: str
    definition: str
    unit: str
    kind: str  # snapshot, flow, level, period
    primary: bool = False
    available: bool = True
    chart: bool = True


INSTALLS_UNAVAILABLE = "Статистика установок недоступна через Telegram API"

SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "telegram_channels",
        "subscribers",
        "Подписчики",
        "Текущее число участников канала по getChatMemberCount на момент снимка. "
        "История — это накопленные снимки, а не восстановленные прошлые дни. "
        "Сумма по каналам считает человека в двух каналах дважды и не является числом уникальных пользователей.",
        "subscribers",
        "snapshot",
        primary=True,
    ),
    MetricSpec(
        "telegram_stickers",
        "sticker_count",
        "Стикеров в наборе",
        "Число стикеров, которое Telegram возвращает в getStickerSet. Это размер набора, а не число установок и не число пользователей.",
        "stickers",
        "snapshot",
        primary=True,
    ),
    MetricSpec(
        "telegram_stickers",
        "installs",
        "Установки набора",
        INSTALLS_UNAVAILABLE,
        "installs",
        "snapshot",
        available=False,
        chart=False,
    ),
    MetricSpec(
        "cloudflare",
        "page_views",
        "Просмотры страниц",
        "Просмотры из Cloudflare Web Analytics (набор rumPageloadEventsAdaptiveGroups, поле count, маяк в браузере, bot: 0). "
        "Это не HTTP-запросы зоны и не уникальные посетители.",
        "views",
        "flow",
        primary=True,
    ),
    MetricSpec(
        "cloudflare",
        "visits",
        "Визиты",
        "Визиты Cloudflare Web Analytics (sum.visits): загрузки страницы, начатые с другого сайта. "
        "Это не уникальные посетители и не HTTP-запросы.",
        "visits",
        "flow",
        primary=True,
    ),
    MetricSpec(
        "cloudflare",
        "unique_visitors",
        "Уникальные посетители",
        "GraphQL-набор Cloudflare Web Analytics не отдаёт уникальных посетителей. Показатель не выводится и не заменяется просмотрами.",
        "visitors",
        "flow",
        available=False,
        chart=False,
    ),
    MetricSpec(
        "cloudflare",
        "http_requests",
        "HTTP-запросы",
        "Запросы к зоне Cloudflare (httpRequests1dGroups, sum.requests), включая автоматический трафик. "
        "Это отдельный показатель и он не складывается с визитами.",
        "requests",
        "flow",
        chart=True,
    ),
    MetricSpec(
        "cloudflare",
        "http_unique_ips",
        "Уникальные IP запросов",
        "uniq.uniques в аналитике зоны: уникальные IP HTTP-запросов, включая ботов. Это не посетители сайта.",
        "ips",
        "flow",
    ),
    MetricSpec(
        "apple",
        "first_time_downloads",
        "Первые загрузки",
        "Сумма Counts в отчёте App Downloads Standard, где Download Type равен First-time Download. "
        "Повторные загрузки, обновления и восстановления сюда не входят. Данные младше двух дней помечены как неполные.",
        "downloads",
        "flow",
        primary=True,
    ),
    MetricSpec(
        "apple",
        "total_downloads",
        "Загрузки без обновлений",
        "First-time Download плюс Redownload из того же отчёта. Обновления и восстановления не включены. "
        "Это не число уникальных пользователей.",
        "downloads",
        "flow",
    ),
    MetricSpec(
        "apple",
        "redownloads",
        "Повторные загрузки",
        "Сумма Counts, где Download Type равен Redownload.",
        "downloads",
        "flow",
        chart=False,
    ),
    MetricSpec(
        "google_play",
        "first_time_installs",
        "Первые установки",
        "Поле Daily User Installs обзорного отчёта Google Play: пользователи, установившие приложение в этот день. "
        "Это не установки на устройства и не текущая аудитория.",
        "users",
        "flow",
        primary=True,
    ),
    MetricSpec(
        "google_play",
        "installed_audience",
        "Установленная аудитория",
        "Поле Current User Installs: пользователи, у которых приложение установлено на эту дату. "
        "Значения по дням не суммируются.",
        "users",
        "level",
    ),
    MetricSpec(
        "google_play",
        "uninstalls",
        "Удаления",
        "Поле Daily User Uninstalls: пользователи, удалившие приложение в этот день.",
        "users",
        "flow",
    ),
    MetricSpec(
        "google_play",
        "device_installs",
        "Установки на устройства",
        "Поле Daily Device Installs. Это устройства, а не пользователи, и показатель не складывается с первыми установками.",
        "devices",
        "flow",
        chart=False,
    ),
    MetricSpec(
        "telegram_bots",
        "requests",
        "Запросы",
        "Число событий, которые бот сам записал модулем телеметрии. Telegram Bot API такую историю не отдаёт.",
        "requests",
        "flow",
        primary=True,
    ),
    MetricSpec(
        "telegram_bots",
        "successful_requests",
        "Успешные запросы",
        "События телеметрии с success=true.",
        "requests",
        "flow",
        chart=False,
    ),
    MetricSpec(
        "telegram_bots",
        "failed_requests",
        "Неуспешные запросы",
        "События телеметрии с success=false.",
        "requests",
        "flow",
        chart=False,
    ),
    MetricSpec(
        "telegram_bots",
        "unique_users",
        "Уникальные пользователи за день",
        "Число разных пользователей бота за сутки. Идентификатор — устойчивый HMAC, в публикацию попадает только количество. "
        "Суточная соль не используется: тот же ключ считает и месяц.",
        "users",
        "flow",
    ),
    MetricSpec(
        "telegram_bots",
        "unique_users_monthly",
        "Уникальные пользователи за месяц",
        "Пользователи, дедуплицированные внутри календарного месяца одним и тем же HMAC, а не объединением суточных хешей.",
        "users",
        "period",
        chart=False,
    ),
    MetricSpec(
        "telegram_bots",
        "duration_ms_sum",
        "Сумма времени обработки",
        "Сумма duration_ms успешных и неуспешных событий за день. На сайте показывается среднее, а не эта сумма.",
        "milliseconds",
        "flow",
        chart=False,
    ),
    MetricSpec(
        "telegram_bots",
        "command_requests",
        "Запросы по событиям",
        "Число событий телеметрии с именем из ограниченного набора символов. Текст сообщений и поисковые запросы сюда не записываются.",
        "requests",
        "flow",
        chart=False,
    ),
    MetricSpec(
        "telegram_bots",
        "duration_count",
        "События с замером времени",
        "Число событий, вошедших в сумму времени обработки.",
        "requests",
        "flow",
        chart=False,
    ),
)

_BY_SOURCE: dict[str, list[MetricSpec]] = {}
for _spec in SPECS:
    _BY_SOURCE.setdefault(_spec.source, []).append(_spec)


def metrics_for(source: str, *, available_only: bool = False) -> list[MetricSpec]:
    rows = _BY_SOURCE.get(source, [])
    if available_only:
        return [row for row in rows if row.available]
    return list(rows)


def get_spec(source: str, metric: str) -> MetricSpec | None:
    for row in _BY_SOURCE.get(source, []):
        if row.metric == metric:
            return row
    return None


def unavailable_for(source: str) -> list[MetricSpec]:
    return [row for row in _BY_SOURCE.get(source, []) if not row.available]
