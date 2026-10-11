"""Логи identity: попытки захвата и подбора видны, личное в лог не идёт."""

import json

import pytest
from structlog.testing import capture_logs

from app.config import settings

OWNER = {"token": "secret-token", "email": "owner@example.com", "password": "password1"}


@pytest.fixture(autouse=True)
def setup_token(monkeypatch):
    monkeypatch.setattr(settings, "setup_token", OWNER["token"])


def events(logs, name):
    return [e for e in logs if e["event"] == name]


async def test_invalid_setup_token_warned(client):
    with capture_logs() as logs:
        await client.post("/setup", json=OWNER | {"token": "guess"})
    [line] = events(logs, "setup.invalid_token")
    assert line["log_level"] == "warning"


async def test_owner_registered(client):
    with capture_logs() as logs:
        await client.post("/setup", json=OWNER)
    [line] = events(logs, "setup.owner_registered")
    assert line["user_id"]


@pytest.mark.parametrize("change", [{"password": "wrong-pass"}, {"email": "nobody@example.com"}])
async def test_login_failed_without_personal_data(client, change):
    await client.post("/setup", json=OWNER)
    with capture_logs() as logs:
        await client.post("/auth/login", json={"email": OWNER["email"], "password": "x"} | change)
    [line] = events(logs, "login.failed")
    assert line["log_level"] == "warning"
    # ни почты, ни пароля: только факт
    assert "example.com" not in repr(logs) and "wrong-pass" not in repr(logs)


async def test_user_id_in_every_line_of_request(client, real_logging, capsys):
    r = await client.post("/setup", json=OWNER)
    token = r.json()["token"]
    real_logging()
    capsys.readouterr()
    await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    [request] = [e for e in lines if e["event"] == "request"]
    assert request["user_id"]
