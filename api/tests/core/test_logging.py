"""Логи: секреты не утекают, у каждого запроса строка с request_id."""

import json
import logging

import pytest
import structlog
from structlog.testing import capture_logs

from app.core.logging import _mask_secrets


def test_secrets_masked():
    event = _mask_secrets(None, "info", {"event": "x", "token": "IGAA", "app_secret": "s", "n": 1})
    assert event == {"event": "x", "token": "***", "app_secret": "***", "n": 1}


async def test_request_logged_with_id(client):
    with capture_logs() as logs:
        r = await client.get("/setup", headers={"x-request-id": "abc"})
    [line] = [e for e in logs if e["event"] == "request"]
    assert line["method"] == "GET" and line["path"] == "/setup" and line["status"] == 200
    assert isinstance(line["ms"], int)
    assert r.headers["x-request-id"] == "abc"


async def test_request_id_generated(client):
    r = await client.get("/setup")
    assert len(r.headers["x-request-id"]) == 32


async def test_query_string_not_logged(client):
    # маркер вебхука приходит в адресе: в лог он попасть не должен
    with capture_logs() as logs:
        await client.get("/setup?hub.verify_token=secret-marker")
    assert "secret-marker" not in repr(logs)


def test_httpx_urls_not_logged():
    # токен Instagram ходит в адресе запроса, а httpx пишет адрес на INFO
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


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


async def test_request_line_logger_name_is_stable(client, real_logging, capsys):
    # по имени логгера ищут в логах: оно не должно зависеть от имени файла
    real_logging()
    capsys.readouterr()
    await client.get("/setup")
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    [request] = [e for e in lines if e["event"] == "request"]
    assert request["logger"] == "app.core"
