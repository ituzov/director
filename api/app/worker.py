"""Фоновый процесс: по кругу зовёт задачи модулей. Своих правил не знает,
только расписание и куда отдавать разобранное."""

import asyncio
import signal
from contextlib import suppress

import structlog

from app import autoreplies, instagram
from app.config import settings
from app.core.logging import setup_logging
from app.db import SessionLocal, engine

# входящих нет: спим. Человек нажал кнопку и ждёт ответ, 2 с поверх доставки
# Meta (1–9 с) почти незаметны, а пустой запрос по частичному индексу копеечный
POLL_SECONDS = 2

# редкие задачи: обновление токенов, позже уборка. Первый раз сразу при старте
PERIODIC_SECONDS = 12 * 60 * 60

# отправителей в Meta одновременно: они почти всё время ждут сеть, а не считают.
# Одно письмо дважды не уйдёт: задачу запирает SKIP LOCKED
SENDERS = 4

# кому отдавать разобранное из входящих
HANDLERS = instagram.InboxHandlers(
    on_comment=autoreplies.handle_comment,
    on_postback=autoreplies.handle_postback,
)
# кому сообщать итог отправки исходящих
ON_RESULT = autoreplies.handle_send_result

log = structlog.get_logger("app.worker")


async def inbox_once(make_session=SessionLocal) -> bool:
    """Разобрать одно входящее в своей сессии и транзакции. False: разбирать нечего."""
    async with make_session() as session:
        return await instagram.process_inbox_event(session, HANDLERS)


async def outbox_once(make_session=SessionLocal) -> bool:
    """Отправить одно исходящее в своей сессии и транзакции. False: отправлять нечего."""
    async with make_session() as session:
        return await instagram.send_outbox_task(session, ON_RESULT)


async def results_once(make_session=SessionLocal) -> bool:
    """Повторить один не дошедший отчёт об итоге отправки. False: повторять нечего."""
    async with make_session() as session:
        return await instagram.report_outbox_result(session, ON_RESULT)


async def periodic(make_session=SessionLocal) -> None:
    """Редкие задачи. Каждая сама решает, кому из аккаунтов пора."""
    async with make_session() as session:
        await instagram.refresh_due_tokens(session)


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    # спим, но SIGTERM будит сразу, а не через seconds
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)


async def run_loop(name: str, once, stop: asyncio.Event) -> None:
    """Делать once, пока есть работа; нет работы, спать. stop проверяем после
    каждого события: остановка не ждёт конца очереди."""
    while not stop.is_set():
        try:
            busy = await once()
        except Exception:
            # база недоступна и прочее вне события: не падаем, ждём и пробуем снова
            log.exception("worker.step_failed", loop=name)
            busy = False
        if not busy:
            await _sleep(stop, POLL_SECONDS)


async def periodic_loop(stop: asyncio.Event) -> None:
    # первый раз сразу при старте
    while not stop.is_set():
        try:
            await periodic()
        except Exception:
            log.exception("worker.periodic_failed")
        await _sleep(stop, PERIODIC_SECONDS)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    # docker stop шлёт SIGTERM: дорабатываем текущие события и выходим
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("worker.started", senders=SENDERS)
    # разбор входящих не ждёт сеть: отправка в Meta идёт своими циклами.
    # Разбор один, чтобы события человека шли по порядку: коммент раньше кнопки
    async with asyncio.TaskGroup() as group:
        group.create_task(run_loop("inbox", inbox_once, stop))
        for number in range(SENDERS):
            group.create_task(run_loop(f"outbox-{number}", outbox_once, stop))
        # не дошедшие отчёты: иначе потерянный итог не узнал бы никто
        group.create_task(run_loop("results", results_once, stop))
        group.create_task(periodic_loop(stop))
    await engine.dispose()
    log.info("worker.stopped")


if __name__ == "__main__":
    setup_logging(settings.log_level, settings.log_json)
    asyncio.run(main())
