"""Логи ключей Meta: видно, что и когда сохранили, сам секрет в лог не идёт."""

import json

import pytest
from structlog.testing import capture_logs

SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


async def test_saved_logged_without_secret(client, owner):
    with capture_logs() as logs:
        await client.put(
            "/instagram/app", headers=owner, json={"app_id": "1", "app_secret": SECRET}
        )
        await client.put("/instagram/app", headers=owner, json={"app_id": "2"})
    first, second = [e for e in logs if e["event"] == "meta_app.saved"]
    assert (first["first"], first["secret_replaced"]) == (True, True)
    assert (second["first"], second["secret_replaced"], second["app_id"]) == (False, False, "2")
    assert SECRET not in repr(logs)


async def test_lines_inside_handler_carry_user_id(client, owner, real_logging, capsys):
    # запись из сервиса знает, кто делает запрос, хотя user_id ей никто не передавал
    real_logging()
    capsys.readouterr()
    await client.put("/instagram/app", headers=owner, json={"app_id": "1", "app_secret": SECRET})
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    [saved] = [e for e in lines if e["event"] == "meta_app.saved"]
    assert saved["user_id"]
