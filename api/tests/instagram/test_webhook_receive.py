"""Приём вебхука: только с подписью нашего секрета, повтор не дублирует событие."""

import hashlib
import hmac
import json

import pytest
from sqlalchemy import func, select
from structlog.testing import capture_logs

from app.instagram import service
from app.instagram.models import InboxEvent

URL = "/webhooks/instagram"
SECRET = "a" * 32
TEXT = "секретное слово из коммента"
BODY = json.dumps(
    {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "time": 1791700000,
                "changes": [{"field": "comments", "value": {"id": "180001", "text": TEXT}}],
            }
        ],
    }
).encode()


def sign(body: bytes, secret: str = SECRET) -> dict:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}"}


@pytest.fixture
async def meta_app(session):
    await service.save_meta_app(session, app_id="1", app_secret=SECRET)


async def inbox(session) -> list[InboxEvent]:
    return list((await session.scalars(select(InboxEvent))).all())


async def test_stored(client, session, meta_app):
    r = await client.post(URL, content=BODY, headers=sign(BODY) | {"x-request-id": "req1"})
    assert r.status_code == 200
    # откат снимает всё незакоммиченное: событие должно было лечь commit-ом,
    # иначе в проде сессия закроется и вебхук пропадёт молча
    await session.rollback()
    [event] = await inbox(session)
    assert (event.kind, event.dedup_key, event.ig_account_id) == (
        "comment",
        "comment:180001",
        "17841400000000000",
    )
    assert event.payload["text"] == TEXT
    # по id запроса worker склеит свои логи с приходом вебхука
    assert event.request_id == "req1"
    assert event.processed_at is None


async def test_repeat_not_duplicated(client, session, meta_app):
    for _ in range(2):
        assert (await client.post(URL, content=BODY, headers=sign(BODY))).status_code == 200
    count = await session.scalar(select(func.count()).select_from(InboxEvent))
    assert count == 1


@pytest.mark.parametrize(
    "headers",
    [
        {},
        sign(BODY, secret="b" * 32),
        {"X-Hub-Signature-256": "sha256=zz"},
        {"X-Hub-Signature-256": "sha256=ё".encode()},
    ],
)
async def test_bad_signature_rejected(client, session, meta_app, headers):
    r = await client.post(URL, content=BODY, headers=headers)
    assert r.status_code == 403
    assert await inbox(session) == []


async def test_signature_over_raw_bytes(client, session, meta_app):
    # тот же JSON другими пробелами: подпись от старых байтов уже не подходит
    reformatted = json.dumps(json.loads(BODY), indent=2).encode()
    r = await client.post(URL, content=reformatted, headers=sign(BODY))
    assert r.status_code == 403


async def test_no_app_rejected(client, session):
    r = await client.post(URL, content=BODY, headers=sign(BODY))
    assert r.status_code == 403


async def test_logs_counts_without_text(client, meta_app):
    with capture_logs() as logs:
        await client.post(URL, content=BODY, headers=sign(BODY))
        await client.post(URL, content=BODY, headers=sign(BODY, secret="b" * 32))
    [received] = [e for e in logs if e["event"] == "webhook.received"]
    assert (received["events"], received["stored"]) == (1, 1)
    [rejected] = [e for e in logs if e["event"] == "webhook.rejected"]
    assert rejected["reason"] == "bad_signature"
    # текст коммента это личные данные: в лог не попадает
    assert TEXT not in repr(logs)


async def test_not_json_accepted_empty(client, session, meta_app):
    # подпись наша, а тело битое: повтор не поможет, отвечаем 200 и ничего не кладём
    body = b"not json"
    r = await client.post(URL, content=body, headers=sign(body))
    assert r.status_code == 200
    assert await inbox(session) == []
