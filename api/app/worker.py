"""Фоновый процесс: по кругу зовёт задачи модулей. Своих правил не знает,
только расписание и куда отдавать разобранное."""

import asyncio
import signal
from contextlib import suppress

import structlog

from app import instagram
from app.config import settings
from app.core.logging import setup_logging
from app.db import SessionLocal, engine

# входящих нет: спим. Meta сама доставляет за 1–9 с, 5 с поверх незаметны
POLL_SECONDS = 5
# событий за круг, потом проверяем, не просят ли остановиться
BATCH = 10

# кому отдавать разобранное. Автоответов ещё нет: комменты только в журнал
HANDLERS = instagram.InboxHandlers()

log = structlog.get_logger("app.worker")


async def run_once(make_session=SessionLocal) -> int:
    """Один круг: до BATCH входящих, каждое в своей сессии и транзакции."""
    handled = 0
    for _ in range(BATCH):
        async with make_session() as session:
            if not await instagram.process_inbox_event(session, HANDLERS):
                break
        handled += 1
    return handled


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    # docker stop шлёт SIGTERM: дорабатываем текущее событие и выходим
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("worker.started")
    while not stop.is_set():
        try:
            handled = await run_once()
        except Exception:
            # база недоступна и прочее вне события: не падаем, ждём и пробуем снова
            log.exception("worker.cycle_failed")
            handled = 0
        if handled == 0:
            # спим, но SIGTERM будит сразу, а не через 5 секунд
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), POLL_SECONDS)
    await engine.dispose()
    log.info("worker.stopped")


if __name__ == "__main__":
    setup_logging(settings.log_level, settings.log_json)
    asyncio.run(main())
