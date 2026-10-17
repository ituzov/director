"""Подключения: сохранение с проверкой ключа, замена, проверка ещё раз, удаление.
Сеть подменена: проверка ключа это запрос списка моделей провайдера."""

import uuid
from datetime import timedelta

import httpx2
import pytest
from sqlalchemy import func, select, update
from structlog.testing import capture_logs

from app.ai import providers, service
from app.ai.exceptions import (
    BaseUrlNotAllowed,
    BaseUrlRequired,
    ConnectionNotFound,
    KeyRejected,
    KeyTooShort,
    UnknownProvider,
)
from app.ai.models import Connection
from app.ai.providers.openai_compatible import OpenAICompatible
from app.core import crypto

KEY = "sk-ant-api03-0123456789abcdefWXYZ"
NEW_KEY = "sk-ant-api03-fedcba9876543210QRST"
USER = uuid.uuid7()
EMPTY = {"data": [], "has_more": False}


class Own(OpenAICompatible):
    kind = "own"
    needs_base_url = True


@pytest.fixture(autouse=True)
def own_provider(monkeypatch):
    monkeypatch.setitem(providers.REGISTRY, "own", Own())


@pytest.fixture
def net(monkeypatch):
    """Подменённая сеть: answer(request) решает ответ, seen копит запросы."""

    class Net:
        seen: list[httpx2.Request] = []
        answer = staticmethod(lambda request: httpx2.Response(200, json=EMPTY))

    async def handler(request):
        Net.seen.append(request)
        result = Net.answer(request)
        return await result if hasattr(result, "__await__") else result

    monkeypatch.setattr(
        service, "_http", lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    Net.seen = []
    return Net


def status(code):
    return lambda request: httpx2.Response(code, json={"type": "error"})


def timeout(request):
    raise httpx2.ReadTimeout("x", request=request)


async def create(session, **kw):
    return await service.create_connection(
        session,
        **{"provider": "anthropic", "name": "Anthropic", "key": KEY, "base_url": None} | kw,
        created_by=USER,
    )


async def count(session) -> int:
    return await session.scalar(select(func.count()).select_from(Connection))


async def test_create_checked(session, net):
    with capture_logs() as logs:
        connection = await create(session, key=f"  {KEY}\n")
    await session.refresh(connection)
    assert crypto.decrypt(connection.key_encrypted) == KEY
    assert connection.key_hint == "WXYZ"
    assert connection.checked_at is not None
    assert (connection.error_code, connection.error_at) == (None, None)
    # проверка ключа это список моделей провайдера с этим ключом
    assert net.seen[0].headers["x-api-key"] == KEY
    # ключа нет в логах ни целиком, ни последними символами
    assert KEY not in str(logs) and "WXYZ" not in str(logs)
    assert [e["event"] for e in logs] == ["ai.connection.created"]


@pytest.mark.parametrize("code", [401, 403])
async def test_rejected_key_not_saved(session, net, code):
    net.answer = status(code)
    with pytest.raises(KeyRejected):
        await create(session)
    assert await count(session) == 0


async def test_no_funds_saved_with_error(session, net):
    # пополнит баланс, и само заработает: сохраняем, карточка красная
    net.answer = status(402)
    connection = await create(session)
    assert (connection.error_code, connection.checked_at) == ("no_funds", None)
    assert connection.error_at is not None


@pytest.mark.parametrize(
    "answer", [timeout, status(500), status(429), status(404)], ids=["timeout", "500", "429", "404"]
)
async def test_unchecked_saved_without_error(session, net, answer):
    # провайдер не ответил толком: «не проверен», карточку не краснит
    net.answer = answer
    connection = await create(session)
    assert (connection.checked_at, connection.error_code, connection.error_at) == (None, None, None)


async def test_unknown_provider(session, net):
    with pytest.raises(UnknownProvider):
        await create(session, provider="openai")
    assert net.seen == []


async def test_base_url_not_allowed_for_known(session, net):
    # иначе ключ Anthropic ушёл бы на чужой адрес
    with pytest.raises(BaseUrlNotAllowed):
        await create(session, base_url="https://evil.test/")
    assert net.seen == []


async def test_own_needs_base_url(session, net):
    with pytest.raises(BaseUrlRequired):
        await create(session, provider="own", base_url="   ")
    connection = await create(session, provider="own", base_url=" http://gpu.local:8000/v1 ")
    assert connection.base_url == "http://gpu.local:8000/v1"
    assert str(net.seen[-1].url) == "http://gpu.local:8000/v1/models"


async def test_short_key(session, net):
    with pytest.raises(KeyTooShort):
        await create(session, key="  sk-short-key  ")
    assert net.seen == []


async def test_empty_name_is_provider(session, net):
    assert (await create(session, name="  ")).name == "anthropic"


async def test_replace_key(session, net):
    net.answer = status(402)
    connection = await create(session)
    before = connection.key_changed_at
    net.answer = lambda request: httpx2.Response(200, json=EMPTY)
    connection = await service.replace_key(session, connection.id, key=NEW_KEY)
    await session.refresh(connection)
    assert crypto.decrypt(connection.key_encrypted) == NEW_KEY
    assert connection.key_hint == "QRST"
    assert connection.key_changed_at > before
    # новый ключ работает: красное снято
    assert (connection.error_code, connection.error_at) == (None, None)
    assert connection.checked_at is not None


async def test_replace_rejected_keeps_old(session, net):
    connection = await create(session)
    net.answer = status(401)
    with pytest.raises(KeyRejected):
        await service.replace_key(session, connection.id, key=NEW_KEY)
    await session.refresh(connection)
    assert crypto.decrypt(connection.key_encrypted) == KEY


async def test_replace_after_delete_during_check(session, net):
    # подключение удалили в другой вкладке, пока проверяли новый ключ: не оживляем
    connection = await create(session)

    async def delete_meanwhile(request):
        await session.execute(Connection.__table__.delete())
        await session.commit()
        return httpx2.Response(200, json=EMPTY)

    net.answer = delete_meanwhile
    with pytest.raises(ConnectionNotFound):
        await service.replace_key(session, connection.id, key=NEW_KEY)
    assert await count(session) == 0


async def test_replace_missing(session, net):
    with pytest.raises(ConnectionNotFound):
        await service.replace_key(session, uuid.uuid7(), key=NEW_KEY)
    assert net.seen == []


@pytest.mark.parametrize(("code", "error"), [(401, "key_rejected"), (402, "no_funds")])
async def test_recheck_writes_card_error(session, net, code, error):
    # ключ уже сохранён: отозвали в панели или кончились деньги, пишем на карточку
    connection = await create(session)
    net.answer = status(code)
    connection = await service.recheck(session, connection.id)
    assert (connection.error_code, connection.checked_at) == (error, None)


async def test_recheck_clears_error(session, net):
    net.answer = status(402)
    connection = await create(session)
    net.answer = lambda request: httpx2.Response(200, json=EMPTY)
    connection = await service.recheck(session, connection.id)
    assert (connection.error_code, connection.error_at) == (None, None)
    assert connection.checked_at is not None


async def test_recheck_timeout_is_unchecked(session, net):
    net.answer = status(402)
    connection = await create(session)
    net.answer = timeout
    connection = await service.recheck(session, connection.id)
    # разовый сбой: про деньги ничего не узнали, красное не держим и не ставим
    assert (connection.error_code, connection.checked_at) == (None, None)


async def test_recheck_unreadable_key(session, net):
    # сменился SECRET_KEY: ключ не расшифровать, владелец вводит заново
    connection = await create(session)
    await session.execute(update(Connection).values(key_encrypted="not-a-fernet-token"))
    await session.commit()
    net.seen.clear()
    connection = await service.recheck(session, connection.id)
    assert connection.error_code == "key_unreadable"
    assert net.seen == []


async def test_recheck_ignores_result_for_replaced_key(session, net):
    # пока проверяли старый ключ, его заменили: итог про старый на карточку не пишем
    connection = await create(session)

    async def replace_meanwhile(request):
        await session.execute(
            update(Connection).values(
                key_changed_at=Connection.key_changed_at + timedelta(seconds=1)
            )
        )
        await session.commit()
        return httpx2.Response(401, json={"type": "error"})

    net.answer = replace_meanwhile
    connection = await service.recheck(session, connection.id)
    assert connection.error_code is None


async def test_rename(session, net):
    connection = await create(session)
    assert (await service.rename(session, connection.id, name=" Основной ")).name == "Основной"


async def test_delete(session, net):
    connection = await create(session)
    with capture_logs() as logs:
        await service.delete_connection(session, connection.id)
    assert await count(session) == 0
    assert [e["event"] for e in logs] == ["ai.connection.deleted"]
    with pytest.raises(ConnectionNotFound):
        await service.delete_connection(session, connection.id)


async def test_list_in_creation_order(session, net):
    first = await create(session, name="Первый")
    second = await create(session, name="Второй")
    assert [c.id for c in await service.list_connections(session)] == [first.id, second.id]


async def test_key_changed_after_check(session, net):
    # вызов, начатый пока проверяли новый ключ, шёл ещё со старым: смена ключа
    # должна быть позже него, иначе его 401 окрасит рабочий новый ключ
    connection = await create(session)
    during = []

    def check(request):
        during.append(service._now())
        return httpx2.Response(200, json=EMPTY)

    net.answer = check
    connection = await service.replace_key(session, connection.id, key=NEW_KEY)
    assert connection.key_changed_at > during[0]
    # а проверку помечаем временем, когда начали проверять
    assert connection.checked_at < during[0]
