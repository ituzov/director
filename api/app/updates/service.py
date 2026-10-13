"""Что доступно для обновления: из списка версий, текущей версии и канала."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx

from app.config import settings
from app.updates import feed
from app.updates.feed import Feed, FeedError, Release, Text
from app.updates.versions import is_newer, parse

# почему кнопки нет, хотя сайт ответил:
# dev: версия установки неизвестна (разработка), сравнивать не с чем;
# channel: в DIRECTOR_CHANNEL опечатка, такого канала на сайте нет;
# min_from: с текущей версии на последнюю напрямую нельзя
type Blocked = Literal["dev", "channel", "min_from"]


@dataclass(frozen=True)
class Available:
    # последняя версия канала, если она новее текущей
    latest: str | None
    # все версии новее текущей до latest, новые сверху: заметки к каждой
    releases: tuple[Release, ...]
    blocked: Blocked | None
    # для blocked="min_from": с какой версии можно прыгнуть на latest
    min_from: str | None


@dataclass(frozen=True)
class UpdateState:
    current: str
    channel: str
    available: Available | None
    message: Text | None
    # сайт не ответил или файл кривой: available и message пустые
    error: Literal["unreachable", "invalid"] | None


def available(data: Feed, *, current: str, channel: str) -> Available:
    """Что предложить установке с версией current на канале channel."""
    if parse(current) is None:
        return Available(latest=None, releases=(), blocked="dev", min_from=None)
    if channel not in data.channels:
        return Available(latest=None, releases=(), blocked="channel", min_from=None)
    latest = data.channels[channel]
    if latest is None or not is_newer(latest, current):
        return Available(latest=None, releases=(), blocked=None, min_from=None)

    # на stable пре-релизы не показываем: их заметки про пробы, а не про релиз
    releases = sorted(
        (
            r
            for r in data.releases
            if is_newer(r.version, current)
            and not is_newer(r.version, latest)
            and (channel == "rc" or "-" not in r.version)
        ),
        key=lambda r: parse(r.version) or (),
        reverse=True,
    )
    target = next(r for r in data.releases if r.version == latest)
    if target.min_from is not None and is_newer(target.min_from, current):
        return Available(
            latest=latest, releases=tuple(releases), blocked="min_from", min_from=target.min_from
        )
    return Available(latest=latest, releases=tuple(releases), blocked=None, min_from=None)


async def check(http: httpx.AsyncClient, now: datetime) -> UpdateState:
    """Состояние для окна обновления. Сайт недоступен: ошибка в ответе, не исключение."""
    current, channel = settings.app_version, settings.director_channel
    try:
        data = await feed.get_feed(http, settings.updates_url, now)
    except FeedError as error:
        return UpdateState(
            current=current, channel=channel, available=None, message=None, error=error.reason
        )
    return UpdateState(
        current=current,
        channel=channel,
        available=available(data, current=current, channel=channel),
        message=data.message,
        error=None,
    )
