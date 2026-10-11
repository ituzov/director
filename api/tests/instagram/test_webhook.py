"""Проверка адреса вебхука: Meta получает challenge только с нашим маркером."""

import pytest
from structlog.testing import capture_logs

from app.instagram import service

URL = "/webhooks/instagram"
CHALLENGE = "1158201444"
# чужой маркер: от нашего отличается, в лог не должен попасть так же, как наш
BAD_TOKEN = "b" * 32


@pytest.fixture
async def verify_token(session) -> str:
    meta_app = await service.save_meta_app(session, app_id="1", app_secret="a" * 32)
    return meta_app.verify_token


def params(token: str, mode: str = "subscribe", challenge: str = CHALLENGE) -> dict:
    return {"hub.mode": mode, "hub.verify_token": token, "hub.challenge": challenge}


async def test_verified(client, verify_token):
    r = await client.get(URL, params=params(verify_token))
    assert (r.status_code, r.text) == (200, CHALLENGE)
    assert r.headers["content-type"].startswith("text/plain")


async def test_wrong_token(client, verify_token):
    r = await client.get(URL, params=params(BAD_TOKEN))
    assert r.status_code == 403
    assert CHALLENGE not in r.text


async def test_wrong_mode(client, verify_token):
    r = await client.get(URL, params=params(verify_token, mode="unsubscribe"))
    assert r.status_code == 403


async def test_no_app(client):
    r = await client.get(URL, params=params(BAD_TOKEN))
    assert r.status_code == 403


async def test_challenge_only_digits(client, verify_token):
    r = await client.get(URL, params=params(verify_token, challenge="<script>"))
    assert r.status_code == 422


async def test_logs_reason_without_token(client, verify_token):
    with capture_logs() as logs:
        await client.get(URL, params=params(BAD_TOKEN))
        await client.get(URL, params=params(verify_token))
    [failed] = [e for e in logs if e["event"] == "webhook.verify_failed"]
    assert failed["reason"] == "bad_token"
    assert any(e["event"] == "webhook.verified" for e in logs)
    assert verify_token not in repr(logs)
    assert BAD_TOKEN not in repr(logs)
