"""Список версий с сайта (versions.json): запрос, проверка формата, кэш в памяти.

Единственное место, где api ходит за версиями. Сюда же потом встанет
телеметрия: тот же запрос раз в час, только из worker и с обезличенными
счётчиками.

Формат тот же, что проверяет check-versions.mjs перед сборкой сайта. Он
не пускает кривой файл на сайт, но api проверяет ещё раз: между нами сеть,
кэш CDN и чужой прокси.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx

from app.updates.versions import parse

# успех держим час, ошибку пять минут: упавший сайт не должен вешать
# каждое открытие админки на таймаут, но и надолго «не проверить» не надо
TTL_OK = timedelta(hours=1)
TTL_ERROR = timedelta(minutes=5)
TIMEOUT = 10.0


@dataclass(frozen=True)
class Text:
    ru: str
    en: str


@dataclass(frozen=True)
class Release:
    version: str
    date: str
    notes: Text
    important: Text | None
    breaking: bool
    security: bool
    # с какой версии можно прыгнуть на эту сразу; None: с любой
    min_from: str | None


@dataclass(frozen=True)
class Feed:
    channels: dict[str, str | None]
    releases: tuple[Release, ...]
    message: Text | None


class FeedError(Exception):
    """Список версий не получить: сайт не ответил или файл кривой."""

    def __init__(self, reason: Literal["unreachable", "invalid"]) -> None:
        super().__init__(reason)
        self.reason = reason


_cache: tuple[datetime, Feed | FeedError] | None = None


async def get_feed(http: httpx.AsyncClient, url: str, now: datetime) -> Feed:
    """Список версий из кэша или с сайта. Не получилось: FeedError."""
    global _cache
    if _cache is not None:
        at, value = _cache
        ttl = TTL_OK if isinstance(value, Feed) else TTL_ERROR
        if now - at < ttl:
            if isinstance(value, FeedError):
                raise value
            return value
    try:
        feed = parse_feed(await _download(http, url))
    except FeedError as error:
        _cache = (now, error)
        raise
    _cache = (now, feed)
    return feed


def reset_cache() -> None:
    """Для тестов: следующий запрос снова пойдёт на сайт."""
    global _cache
    _cache = None


async def _download(http: httpx.AsyncClient, url: str) -> Any:
    try:
        response = await http.get(url, timeout=TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise FeedError("unreachable") from error
    try:
        return response.json()
    except ValueError as error:
        raise FeedError("invalid") from error


def parse_feed(data: Any) -> Feed:
    """Разобрать versions.json. Любое отступление от формата: FeedError("invalid")."""
    try:
        if data["schema"] != 1:
            raise ValueError("schema")
        releases = tuple(_release(item) for item in data["versions"])
        known = {r.version for r in releases}
        channels: dict[str, str | None] = {}
        for name in ("stable", "rc"):
            latest = data["channels"][name]
            if latest is not None and latest not in known:
                raise ValueError(name)
            channels[name] = latest
        return Feed(channels=channels, releases=releases, message=_text_or_none(data["message"]))
    except (KeyError, TypeError, ValueError) as error:
        raise FeedError("invalid") from error


def _release(item: dict[str, Any]) -> Release:
    version, min_from = item["version"], item["min_from"]
    if parse(version) is None or (min_from is not None and parse(min_from) is None):
        raise ValueError(version)
    if not isinstance(item["breaking"], bool) or not isinstance(item["security"], bool):
        raise ValueError(version)
    return Release(
        version=version,
        date=_str(item["date"]),
        notes=_text(item["notes"]),
        important=_text_or_none(item["important"]),
        breaking=item["breaking"],
        security=item["security"],
        min_from=min_from,
    )


def _text(value: Any) -> Text:
    return Text(ru=_str(value["ru"]), en=_str(value["en"]))


def _text_or_none(value: Any) -> Text | None:
    return None if value is None else _text(value)


def _str(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty")
    return value
