"""Что доступно для обновления: из списка версий, текущей версии и канала."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import httpx
import structlog

from app.config import settings
from app.updates import feed, host
from app.updates.exceptions import Busy, NotAvailable, NotInstalled
from app.updates.feed import Feed, FeedError, Release, Text
from app.updates.versions import is_newer, parse

log = structlog.get_logger("app.updates")

# просьба лежит дольше: systemd её не забирает, юнит на хосте не работает
STUCK_AFTER = timedelta(minutes=1)
# столько строк лога показываем, когда обновление упало
LOG_TAIL = 30

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


# idle: обновлений не было; queued: просьба в лотке; stuck: лежит, но хост её не
# забирает; running: идёт шаг; done и failed: итог последнего обновления
type Phase = Literal["idle", "queued", "stuck", "running", "done", "failed"]


@dataclass(frozen=True)
class UpdateStatus:
    phase: Phase
    # строка с доски как есть: «pull 0.1.1», «done 0.1.0 -> 0.1.1»
    step: str | None
    at: datetime | None
    # хвост лога только у failed: по нему видно, что сломалось
    log: tuple[str, ...]


def status(now: datetime) -> UpdateStatus:
    """Как идёт обновление: по лотку и доске хоста."""
    waiting = host.request_waiting_since(settings.updates_request_dir)
    if waiting is not None:
        phase: Phase = "stuck" if now - waiting > STUCK_AFTER else "queued"
        return UpdateStatus(phase=phase, step=None, at=waiting, log=())
    board = host.read_board(settings.updates_run_dir)
    if board is None:
        return UpdateStatus(phase="idle", step=None, at=None, log=())
    word = board.text.split(maxsplit=1)[0]
    if word == "done":
        return UpdateStatus(phase="done", step=board.text, at=board.at, log=())
    if word in ("failed", "error:"):
        tail = host.read_log_tail(settings.updates_run_dir, LOG_TAIL)
        return UpdateStatus(phase="failed", step=board.text, at=board.at, log=tail)
    return UpdateStatus(phase="running", step=board.text, at=board.at, log=())


async def request_update(http: httpx.AsyncClient, now: datetime, version: str) -> UpdateStatus:
    """Попросить хост обновить до version. Только до последней доступной версии."""
    if not settings.updates_request_dir.is_dir():
        raise NotInstalled
    if status(now).phase in ("queued", "stuck", "running"):
        raise Busy
    state = await check(http, now)
    offer = state.available
    if offer is None or offer.blocked is not None or offer.latest != version:
        raise NotAvailable
    host.write_request(settings.updates_request_dir, version)
    log.info("update.requested", current=state.current, version=version)
    return status(now)
