"""Ручки «Настройки → ИИ»: ключ наружу не уходит, ошибки становятся кодами,
менять может тот, кто подключает аккаунты, итог проверки отдельно от карточки.
Сеть провайдера подменена."""

import uuid
from datetime import UTC, datetime

import httpx2
import pytest
from sqlalchemy import func, select

from app.ai import service
from app.ai.models import Binding, Connection

KEY = "sk-ant-api03-0123456789abcdefWXYZ"
NEW_KEY = "sk-ant-api03-fedcba9876543210QRST"
EMPTY = {"data": [], "has_more": False}


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


@pytest.fixture
def net(monkeypatch):
    """answer(request) решает, что ответит провайдер."""

    class Net:
        answer = staticmethod(lambda request: httpx2.Response(200, json=EMPTY))

    monkeypatch.setattr(
        service,
        "_http",
        lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: Net.answer(r))),
    )
    return Net


def status(code):
    return lambda request: httpx2.Response(code, json={"type": "error"})


def timeout(request):
    raise httpx2.ReadTimeout("x", request=request)


async def create(client, headers, **kw):
    body = {"provider": "anthropic", "name": "Основной", "key": KEY} | kw
    return await client.post("/ai/connections", headers=headers, json=body)


async def count(session) -> int:
    return await session.scalar(select(func.count()).select_from(Connection))


async def test_create_and_list(client, owner, net):
    r = await create(client, owner)
    assert r.status_code == 201
    body = r.json()
    assert body["check"] == "ok"
    card = body["connection"]
    assert (card["provider"], card["name"], card["key_hint"]) == ("anthropic", "Основной", "WXYZ")
    assert card["checked_at"] is not None and card["error_code"] is None
    assert card["tasks"] == []
    assert (await client.get("/ai/connections", headers=owner)).json() == [card]


async def test_providers(client, owner):
    r = await client.get("/ai/providers", headers=owner)
    kinds = {p["kind"]: p["needs_base_url"] for p in r.json()}
    assert kinds == {"anthropic": False, "timeweb": False}


async def test_key_never_leaves(client, owner, net, real_logging, capsys):
    # ни ответ, ни лог не несут ключ: только последние 4 символа на карточке
    real_logging()
    card = (await create(client, owner)).json()["connection"]
    responses = [
        await client.get("/ai/connections", headers=owner),
        await client.put(f"/ai/connections/{card['id']}/key", headers=owner, json={"key": NEW_KEY}),
        await client.post(f"/ai/connections/{card['id']}/check", headers=owner),
        await client.patch(f"/ai/connections/{card['id']}", headers=owner, json={"name": "x"}),
    ]
    logs = capsys.readouterr().err
    assert "ai.connection.created" in logs
    for secret in (KEY, NEW_KEY, KEY[:-4], NEW_KEY[:-4]):
        assert secret not in logs
        assert all(secret not in r.text for r in responses)


@pytest.mark.parametrize(
    ("kw", "detail"),
    [
        ({"provider": "openai"}, "UnknownProvider"),
        ({"base_url": "https://evil.example/v1"}, "BaseUrlNotAllowed"),
        ({"key": "short"}, "KeyTooShort"),
    ],
)
async def test_form_errors(client, owner, net, session, kw, detail):
    r = await create(client, owner, **kw)
    assert (r.status_code, r.json()) == (422, {"detail": detail})
    assert await count(session) == 0


@pytest.mark.parametrize("code", [401, 403])
async def test_rejected_key_not_saved(client, owner, net, session, code):
    net.answer = status(code)
    r = await create(client, owner)
    assert (r.status_code, r.json()) == (422, {"detail": "KeyRejected"})
    assert await count(session) == 0


async def test_key_too_long(client, owner, net, session):
    # предел схемы: огромное тело не уходит ни на шифрование, ни провайдеру
    r = await create(client, owner, key="k" * 501)
    assert r.status_code == 422
    assert await count(session) == 0


async def test_unchecked_saved_with_check_result(client, owner, net):
    # провайдер не ответил: подключение сохранено, карточка «не проверена»,
    # а экран узнаёт почему
    net.answer = timeout
    r = await create(client, owner)
    assert r.status_code == 201
    assert r.json()["check"] == "timeout"
    card = r.json()["connection"]
    assert (card["checked_at"], card["error_code"]) == (None, None)


async def test_recheck_result(client, owner, net):
    card = (await create(client, owner)).json()["connection"]
    net.answer = status(402)
    r = await client.post(f"/ai/connections/{card['id']}/check", headers=owner)
    assert r.json()["check"] == "no_funds"
    assert r.json()["connection"]["error_code"] == "no_funds"
    net.answer = timeout
    r = await client.post(f"/ai/connections/{card['id']}/check", headers=owner)
    # разовый сбой: карточка прежняя, итог говорит, что проверка не прошла
    assert (r.json()["check"], r.json()["connection"]["error_code"]) == ("timeout", "no_funds")


async def test_replace_key(client, owner, net):
    card = (await create(client, owner)).json()["connection"]
    r = await client.put(f"/ai/connections/{card['id']}/key", headers=owner, json={"key": NEW_KEY})
    assert (r.json()["check"], r.json()["connection"]["key_hint"]) == ("ok", "QRST")
    net.answer = status(401)
    r = await client.put(f"/ai/connections/{card['id']}/key", headers=owner, json={"key": KEY})
    assert (r.status_code, r.json()) == (422, {"detail": "KeyRejected"})


async def test_rename_and_delete(client, owner, net, session):
    card = (await create(client, owner)).json()["connection"]
    url = f"/ai/connections/{card['id']}"
    r = await client.patch(url, headers=owner, json={"name": " Запасной "})
    assert r.json()["name"] == "Запасной"
    assert (await client.delete(url, headers=owner)).status_code == 204
    assert await count(session) == 0


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PUT", "/key", {"key": NEW_KEY}),
        ("POST", "/check", None),
        ("PATCH", "", {"name": "x"}),
        ("DELETE", "", None),
    ],
)
async def test_not_found(client, owner, net, method, path, body):
    url = f"/ai/connections/{uuid.uuid7()}{path}"
    r = await client.request(method, url, headers=owner, json=body)
    assert (r.status_code, r.json()) == (404, {"detail": "ConnectionNotFound"})


WRITES = [
    ("POST", "", {"provider": "anthropic", "key": KEY}),
    ("PUT", "/{id}/key", {"key": NEW_KEY}),
    ("POST", "/{id}/check", None),
    ("PATCH", "/{id}", {"name": "x"}),
    ("DELETE", "/{id}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_member_reads_but_cannot_change(
    client, owner, login_as, net, session, method, path, body
):
    card = (await create(client, owner)).json()["connection"]
    member = await login_as("member")
    assert (await client.get("/ai/connections", headers=member)).status_code == 200
    assert (await client.get("/ai/providers", headers=member)).status_code == 200
    url = "/ai/connections" + path.format(id=card["id"])
    r = await client.request(method, url, headers=member, json=body)
    assert r.status_code == 403
    # ничего не поменялось: не добавилось, не переименовалось, ключ прежний
    [after] = (await client.get("/ai/connections", headers=owner)).json()
    assert (after["name"], after["key_hint"]) == ("Основной", "WXYZ")


@pytest.mark.parametrize(("method", "path", "body"), [("GET", "", None), *WRITES])
async def test_anonymous(client, net, method, path, body):
    url = "/ai/connections" + path.format(id=uuid.uuid7())
    assert (await client.request(method, url, json=body)).status_code == 401
    assert (await client.get("/ai/providers")).status_code == 401


async def test_tasks_on_card(client, owner, net, session):
    card = (await create(client, owner)).json()["connection"]
    connection_id = uuid.UUID(card["id"])
    session.add_all(
        [
            Binding(
                purpose="assistant.answer", scope="a1", connection_id=connection_id, model="m1"
            ),
            Binding(
                purpose="assistant.answer",
                scope="a2",
                connection_id=connection_id,
                model="m2",
                model_missing_at=datetime.now(UTC),
            ),
            Binding(
                purpose="assistant.answer", scope=None, connection_id=connection_id, model="m1"
            ),
            Binding(purpose="assistant.topic", scope=None, connection_id=connection_id, model="m1"),
        ]
    )
    await session.commit()
    [card] = (await client.get("/ai/connections", headers=owner)).json()
    assert card["tasks"] == [
        {
            "purpose": "assistant.answer",
            "scopes": 3,
            "models": ["m1", "m2"],
            "model_missing": True,
        },
        {"purpose": "assistant.topic", "scopes": 1, "models": ["m1"], "model_missing": False},
    ]
