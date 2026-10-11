"""Проверка адреса вебхука: Meta получает challenge только с нашим маркером."""

from datetime import UTC, datetime

import pytest
from structlog.testing import capture_logs

from app.instagram import repository, service

URL = "/webhooks/instagram"
CHALLENGE = "1158201444"
# чужой маркер: от нашего отличается, в лог не должен попасть так же, как наш
BAD_TOKEN = "b" * 32
OLD = datetime(2000, 1, 1, tzinfo=UTC)


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


async def test_meta_marks_verified(client, session, verify_token):
    meta_app = await repository.get_meta_app(session)
    assert meta_app.webhook_verified_at is None
    # тест целиком в одной транзакции, а now() в ней не движется: состарим время руками
    meta_app.updated_at = OLD
    await session.commit()

    await client.get(URL, params=params(verify_token))
    await session.refresh(meta_app)
    assert meta_app.webhook_verified_at is not None
    # подтверждение это не смена ключей: «Ключи обновлены» в админке не сдвигается
    assert meta_app.updated_at == OLD


async def test_self_check_not_marked(client, session, verify_token):
    # самопроверка админки отвечает так же, но за Meta себя не выдаёт
    r = await client.get(URL, params=params(verify_token, mode="check"))
    assert (r.status_code, r.text) == (200, CHALLENGE)
    meta_app = await repository.get_meta_app(session)
    await session.refresh(meta_app)
    assert meta_app.webhook_verified_at is None
