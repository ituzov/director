"""Логи api и worker: structlog поверх стандартного logging.

Через один форматтер идут все записи, и наши, и uvicorn с SQLAlchemy:
в терминале цветные строки, в контейнере одна строка JSON на событие.
Контекст (request_id, account_id) кладётся bind_contextvars и попадает
во все записи ниже по стеку, в любом модуле.
"""

import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from structlog.typing import Processor

# ключи, значения которых в лог не попадают никогда, даже если их передали по ошибке
_SECRETS = {"authorization", "token", "access_token", "app_secret", "secret", "password"}

# имя логгера постоянное, по нему ищут в логах: при переезде файла не меняется
log = structlog.get_logger("app.core")


def _mask_secrets(_logger: object, _method: str, event: dict) -> dict:
    for key in event.keys() & _SECRETS:
        event[key] = "***"
    return event


def setup_logging(level: str = "INFO", json: bool | None = None) -> None:
    # не сказали явно: в терминале строки для глаз, иначе (docker) JSON
    if json is None:
        json = not sys.stderr.isatty()

    # общее для наших записей и чужих (uvicorn, SQLAlchemy)
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _mask_secrets,
    ]
    structlog.configure(
        processors=[
            *shared,
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # без кэша: он запоминает настройки при первом вызове, и capture_logs в
        # тестах перестаёт видеть записи. Выигрыш от кэша для нас копеечный
        cache_logger_on_first_use=False,
    )
    renderer: list[Processor] = (
        [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
        if json
        else [structlog.dev.ConsoleRenderer()]
    )
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderer],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn вешает свои обработчики: его записи отдаём корню, в общий формат
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    # access-лог uvicorn выключаем: запросы пишет log_requests, с request_id
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
    # httpx на INFO пишет полный адрес запроса, а токен Instagram ходит в нём
    # (?access_token=...). Вызовы Meta логируем сами, без строки запроса
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Middleware: строка на запрос и request_id в контексте всех записей запроса.

    Пишем только путь, без строки запроса: в проверке вебхука Meta кладёт
    маркер прямо в адрес (?hub.verify_token=...).
    """
    # id приходит от Caddy (X-Request-ID), без него придумываем свой
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    # контекст прошлого запроса не должен протечь в этот
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request.failed", method=request.method, path=request.url.path)
        raise
    # healthcheck дёргается раз в несколько секунд: в обычном логе он шум
    level = logging.DEBUG if request.url.path == "/health" else logging.INFO
    log.log(
        level,
        "request",
        # поля, которые оставили по дороге (user_id от identity): контекст ручки
        # живёт в дочерней задаче, и сюда он сам не возвращается
        **getattr(request.state, "log_context", {}),
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000),
    )
    response.headers["x-request-id"] = request_id
    return response
