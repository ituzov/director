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

# кому отдавать разобранное из входящих
HANDLERS = instagram.InboxHandlers(on_comment=autoreplies.handle_comment)
# кому сообщать итог отправки исходящих
ON_RESULT = autoreplies.handle_send_result

log = structlog.get_logger("app.worker")


async def step(make_session=SessionLocal) -> bool:
    """Один шаг: одно входящее и одно исходящее, каждое в своей сессии и транзакции.
    False: делать нечего ни там, ни там."""
    async with make_session() as session:
        received = await instagram.process_inbox_event(session, HANDLERS)
    async with make_session() as session:
        sent = await instagram.send_outbox_task(session, ON_RESULT)
    return received or sent


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    # docker stop шлёт SIGTERM: дорабатываем текущее событие и выходим
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("worker.started")
    # stop проверяем после каждого события: остановка не ждёт конца очереди
    while not stop.is_set():
        try:
            busy = await step()
        except Exception:
            # база недоступна и прочее вне события: не падаем, ждём и пробуем снова
            log.exception("worker.step_failed")
            busy = False
        if not busy:
            # спим, но SIGTERM будит сразу, а не через 5 секунд
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), POLL_SECONDS)
    await engine.dispose()
    log.info("worker.stopped")


if __name__ == "__main__":
    setup_logging(settings.log_level, settings.log_json)
    asyncio.run(main())
