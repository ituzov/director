"""Логи: секреты не утекают, у каждого запроса строка с request_id."""

import json
import logging

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from structlog.testing import capture_logs

from app.core.logging import _mask_secrets


@pytest.mark.parametrize("name", ["token", "app_secret", "key", "api_key"])
def test_secrets_masked(name):
    event = _mask_secrets(None, "info", {"event": "x", name: "IGAA", "n": 1})
    assert event == {"event": "x", name: "***", "n": 1}


async def test_request_logged_with_id(client):
    with capture_logs() as logs:
        r = await client.get("/setup", headers={"x-request-id": "abc"})
    [line] = [e for e in logs if e["event"] == "request"]
    assert line["method"] == "GET" and line["path"] == "/setup" and line["status"] == 200
    assert isinstance(line["ms"], int)
    assert r.headers["x-request-id"] == "abc"


async def test_odd_request_id_replaced(client):
    # мусор и простыни в заголовке не попадают ни в логи, ни в inbox
    for odd in ("a" * 65, "a b", "<script>"):
        r = await client.get("/setup", headers={"x-request-id": odd})
        assert len(r.headers["x-request-id"]) == 32
        assert r.headers["x-request-id"] != odd


async def test_request_id_generated(client):
    r = await client.get("/setup")
    assert len(r.headers["x-request-id"]) == 32


async def test_query_string_not_logged(client):
    # маркер вебхука приходит в адресе: в лог он попасть не должен
    with capture_logs() as logs:
        await client.get("/setup?hub.verify_token=secret-marker")
    assert "secret-marker" not in repr(logs)


@pytest.mark.parametrize(
    "name", ["httpx", "httpcore", "httpx2", "httpcore2", "openai", "anthropic"]
)
def test_http_clients_quiet(name):
    # токен Instagram ходит в адресе запроса, а httpx пишет адрес на INFO;
    # SDK моделей на DEBUG пишут параметры запроса, а там комменты людей
    assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_secrets_masked_in_output(real_logging, capsys):
    # не функция сама по себе, а то, что реально уходит в stderr
    real_logging()
    structlog.get_logger("test").info("call", token="IGAA-real-token")
    err = capsys.readouterr().err
    assert "IGAA-real-token" not in err
    assert '"token": "***"' in err


async def test_health_is_debug(client):
    # healthcheck раз в несколько секунд: на INFO он забил бы лог
    with capture_logs() as logs:
        await client.get("/health")
    [line] = [e for e in logs if e["event"] == "request"]
    assert line["log_level"] == "debug"


async def test_context_does_not_leak(client):
    # контекст прошлого запроса не попадает в следующий
    await client.get("/setup", headers={"x-request-id": "first"})
    structlog.contextvars.bind_contextvars(account_id="leftover")
    await client.get("/setup", headers={"x-request-id": "second"})
    assert structlog.contextvars.get_contextvars() == {"request_id": "second"}


async def test_failed_request_logged(client):
    # падение в ручке: строка request.failed с трейсом, исключение летит дальше
    from app.main import app

    @app.get("/boom-for-test")
    async def boom():
        raise RuntimeError("boom")

    try:
        with capture_logs() as logs, pytest.raises(RuntimeError):
            await client.get("/boom-for-test", headers={"x-request-id": "r1"})
    finally:
        app.router.routes.pop()
    [line] = [e for e in logs if e["event"] == "request.failed"]
    assert line["path"] == "/boom-for-test" and line["exc_info"] is True


def test_uvicorn_goes_to_common_format(real_logging, capsys):
    real_logging()
    logging.getLogger("uvicorn.error").info("server started")
    logging.getLogger("uvicorn.access").info("GET / 200")
    err = capsys.readouterr().err
    # своя запись uvicorn в нашем JSON, а его access-лог молчит: запросы пишем сами
    assert '"logger": "uvicorn.error"' in err
    assert "GET / 200" not in err


def test_uvicorn_color_copy_dropped(real_logging, capsys):
    real_logging()
    logging.getLogger("uvicorn.error").info("started", extra={"color_message": "\x1b[36mstarted"})
    [entry] = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert entry["event"] == "started"
    assert "color_message" not in entry


async def test_request_line_logger_name_is_stable(client, real_logging, capsys):
    # по имени логгера ищут в логах: оно не должно зависеть от имени файла
    real_logging()
    capsys.readouterr()
    await client.get("/setup")
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    [request] = [e for e in lines if e["event"] == "request"]
    assert request["logger"] == "app.core"


# значение, которое лежит в локальной переменной упавшей функции
LOCAL_SECRET = "local-secret-value"


@pytest.mark.parametrize("as_json", [True, False])
def test_traceback_without_locals(real_logging, capsys, as_json):
    # трейсбек есть, а значений из кадров нет: там секрет Meta, токены и тела вебхуков
    real_logging(json=as_json)

    def connect(app_secret: str) -> None:
        raise RuntimeError("boom")

    try:
        connect(LOCAL_SECRET)
    except RuntimeError:
        structlog.get_logger("app.test").exception("failed")
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "connect" in err
    assert LOCAL_SECRET not in err


async def test_sql_error_without_parameters(session):
    # SQLAlchemy не кладёт значения запроса в текст ошибки. Ошибка тут «деление на ноль»:
    # её Postgres пишет без значений, а ошибку разбора значения он повторяет сам
    with pytest.raises(DBAPIError) as info:
        await session.execute(text("SELECT CAST(:value AS text), 1 / 0"), {"value": LOCAL_SECRET})
    assert "SELECT CAST" in str(info.value)
    assert LOCAL_SECRET not in str(info.value)
