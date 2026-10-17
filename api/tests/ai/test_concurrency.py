"""Замки и транзакции ai на настоящих соединениях: песочница одного соединения
их не покажет. Настоящие коммиты, после теста уборка."""

import asyncio
import contextlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from pydantic_ai import Agent
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app import ai
from app.ai import calls, providers, repository, service
from app.ai.models import Binding, Call, Connection
from app.ai.providers.base import NO_FUNDS, ProviderError
from app.core import crypto
from app.db import make_engine
from tests.conftest import TEST_DATABASE_URL

KEY = "sk-test-key-0123456789abcdef"
EMPTY = {"data": [], "has_more": False}


@pytest.fixture
async def sessions():
    engine = make_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE ai.call, ai.binding, ai.connection CASCADE"))
    await engine.dispose()


async def add_connection(sessions, provider="timeweb", **kw) -> uuid.UUID:
    async with sessions() as session:
        connection = Connection(
            **{
                "provider": provider,
                "name": provider,
                "key_encrypted": crypto.encrypt(KEY),
                "key_hint": KEY[-4:],
                "key_changed_at": datetime.now(UTC) - timedelta(hours=1),
                "created_by": uuid.uuid7(),
            }
            | kw
        )
        session.add(connection)
        await session.commit()
        return connection.id


async def card(sessions, connection_id):
    async with sessions() as session:
        c = await session.get(Connection, connection_id)
        return c.checked_at, c.error_code, c.error_at


async def test_two_results_at_once_not_mixed(sessions, monkeypatch):
    # ошибка (начата раньше) и успех (начат позже) пишутся разом. Без замка оба
    # прочитают одну строку, и успех запишет только checked_at: «проверен» и
    # «нет денег» сразу. С замком второй читает уже записанное первым
    connection_id = await add_connection(
        sessions, checked_at=datetime.now(UTC) - timedelta(hours=1)
    )
    async with sessions() as session:
        key_changed_at = (await session.get(Connection, connection_id)).key_changed_at
    target = calls._Target(
        "assistant.answer",
        None,
        connection_id,
        providers.get("timeweb"),
        "m",
        KEY,
        None,
        key_changed_at,
    )
    barrier = asyncio.Barrier(2)
    read = repository.get_connection

    async def read_then_wait(session, connection_id, *, lock=False):
        connection = await read(session, connection_id, lock=lock)
        # с замком второй сюда не дойдёт, пока первый не закоммитит: не ждём вечно
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(barrier.wait(), 0.5)
        return connection

    monkeypatch.setattr(repository, "get_connection", read_then_wait)
    now = datetime.now(UTC)
    error = ProviderError(NO_FUNDS, 402)
    await asyncio.gather(
        calls._record(sessions, target, now - timedelta(seconds=2), time.monotonic(), None, error),
        calls._record(sessions, target, now, time.monotonic(), None, None),
    )
    assert await card(sessions, connection_id) == (now, None, None)


class Locks:
    """Из соседнего соединения: можно ли сейчас взять таблицу подключений целиком.
    Чтение в открытой транзакции держит на ней замок до её конца."""

    def __init__(self, sessions) -> None:
        self.sessions = sessions
        self.free: list[bool] = []

    async def probe(self) -> None:
        async with self.sessions() as session:
            try:
                await session.execute(
                    text("LOCK TABLE ai.connection IN ACCESS EXCLUSIVE MODE NOWAIT")
                )
                self.free.append(True)
            except DBAPIError:
                self.free.append(False)
            await session.rollback()


@pytest.fixture
def net(monkeypatch, sessions):
    locks = Locks(sessions)

    async def handler(request):
        await locks.probe()
        return httpx2.Response(200, json=EMPTY)

    monkeypatch.setattr(
        service, "_http", lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    return locks


@pytest.mark.parametrize("action", ["create", "replace", "recheck"])
async def test_no_transaction_during_key_check(sessions, net, action):
    # пока провайдер проверяет ключ (до 15 с), подключения не заперты, даже если
    # ручка до этого уже читала из той же сессии
    connection_id = await add_connection(sessions, provider="anthropic")
    async with sessions() as session:
        seen = await service.list_connections(session)
        if action == "create":
            await service.create_connection(
                session,
                provider="anthropic",
                name="x",
                key=KEY,
                base_url=None,
                created_by=uuid.uuid7(),
            )
        elif action == "replace":
            await service.replace_key(session, connection_id, key=KEY + "new")
        else:
            await service.recheck(session, connection_id)
        # прочитанное ручкой до вызова не протухло: обращение без перечитывания
        assert seen[0].name == "anthropic"
    assert net.free == [True]


def completion(request):
    body = json.loads(request.content)
    return httpx2.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 1,
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ок"},
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        },
    )


async def test_run_on_real_sessions(sessions, monkeypatch):
    # ai.run берёт свои сессии: настройка читается, журнал и карточка пишутся
    # отдельными коммитами, а пока модель думает, подключения не заперты
    connection_id = await add_connection(sessions)
    async with sessions() as session:
        await ai.set_binding(
            session, purpose="assistant.answer", scope=None, connection_id=connection_id, model="m"
        )
        await session.commit()
    locks = Locks(sessions)

    async def handler(request):
        await locks.probe()
        return completion(request)

    monkeypatch.setattr(
        calls, "_http", lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    result = await ai.run(
        purpose="assistant.answer", scope=None, agent=Agent(), prompt="?", make_session=sessions
    )
    assert result.output == "ок"
    assert locks.free == [True]
    async with sessions() as session:
        [call] = list(await session.scalars(select(Call)))
    assert (call.outcome, call.connection_id) == ("ok", connection_id)
    assert (await card(sessions, connection_id))[0] is not None


async def test_recheck_vs_replace_between_read_and_write(sessions, monkeypatch):
    # recheck старого ключа получил 402 и перечитывает строку, чтобы записать итог.
    # Ровно в этот момент владелец заменил ключ. Без замка на перечитывании замена
    # успеет закоммитить, и «нет денег» старого ключа ляжет на новый, рабочий
    connection_id = await add_connection(sessions, provider="anthropic")
    new_key = KEY + "new"

    def handler(request):
        if request.headers["x-api-key"] == KEY:
            return httpx2.Response(402, json={"type": "error"})
        return httpx2.Response(200, json=EMPTY)

    monkeypatch.setattr(
        service, "_http", lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    get = service._get
    armed = [True]

    async def get_then_replace(session, connection_id, *, lock=False):
        connection = await get(session, connection_id, lock=lock)
        if lock and armed[0]:
            armed[0] = False

            async def replace():
                async with sessions() as other:
                    await service.replace_key(other, connection_id, key=new_key)

            replacing = asyncio.create_task(replace())
            # с замком замена ждёт, пока recheck не закоммитит: не ждём её здесь
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(replacing), 0.5)
            get_then_replace.replacing = replacing
        return connection

    monkeypatch.setattr(service, "_get", get_then_replace)
    async with sessions() as session:
        await service.recheck(session, connection_id)
    await get_then_replace.replacing
    async with sessions() as session:
        connection = await session.get(Connection, connection_id)
        assert crypto.decrypt(connection.key_encrypted) == new_key
        # итог про новый ключ: проверен, без ошибки старого
        assert (connection.error_code, connection.checked_at is not None) == (None, True)


@pytest.fixture
def ok_net(monkeypatch):
    monkeypatch.setattr(
        service,
        "_http",
        lambda: httpx2.AsyncClient(
            transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=EMPTY))
        ),
    )


@pytest.mark.parametrize("where", ["run", "recheck"])
@pytest.mark.parametrize("meanwhile", ["replace", "delete"])
async def test_unreadable_vs_change_between_read_and_write(
    sessions, monkeypatch, ok_net, where, meanwhile
):
    # ключ не расшифровать (сменился SECRET_KEY), и ровно между чтением строки и
    # записью «не расшифровать» владелец заменил ключ или удалил подключение
    connection_id = await add_connection(sessions, provider="anthropic", key_encrypted="bad")
    async with sessions() as session:
        await ai.set_binding(
            session, purpose="p", scope=None, connection_id=connection_id, model="m"
        )
        await session.commit()
    new_key = KEY + "new"

    async def change():
        async with sessions() as other:
            if meanwhile == "replace":
                await service.replace_key(other, connection_id, key=new_key)
            else:
                await service.delete_connection(other, connection_id)

    read = repository.get_connection
    armed = [True]

    async def change_then_read(session, connection_id, *, lock=False):
        if lock and armed[0]:
            armed[0] = False
            await change()
        return await read(session, connection_id, lock=lock)

    monkeypatch.setattr(repository, "get_connection", change_then_read)
    async with sessions() as session:
        if where == "run":
            with pytest.raises(ai.AiCallFailed) as caught:
                await ai.run(
                    purpose="p", scope=None, agent=Agent(), prompt="?", make_session=sessions
                )
            want = "key_unreadable" if meanwhile == "replace" else "not_configured"
            assert caught.value.code == want
        elif meanwhile == "replace":
            await service.recheck(session, connection_id)
        else:
            with pytest.raises(service.ConnectionNotFound):
                await service.recheck(session, connection_id)
    if meanwhile == "replace":
        async with sessions() as session:
            connection = await session.get(Connection, connection_id)
        # новый ключ рабочий: «не расшифровать» про старый на нём нет
        assert crypto.decrypt(connection.key_encrypted) == new_key
        assert connection.error_code is None and connection.checked_at is not None


async def test_set_binding_vs_delete(sessions, monkeypatch):
    # подключение удаляют, пока задаче выбирают модель на нём. С замком удаление
    # ждёт: настройка записалась, потом удаление сделало её «не настроенной».
    # Без замка запись упала бы на внешнем ключе
    connection_id = await add_connection(sessions)
    get = service._get
    armed = [True]

    async def get_then_delete(session, connection_id, *, lock=False):
        connection = await get(session, connection_id, lock=lock)
        # удаление само ходит через _get: запускаем его один раз
        if not armed[0]:
            return connection
        armed[0] = False

        async def delete():
            async with sessions() as other:
                await service.delete_connection(other, connection_id)

        get_then_delete.deleting = asyncio.create_task(delete())
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(get_then_delete.deleting), 0.5)
        return connection

    monkeypatch.setattr(service, "_get", get_then_delete)
    async with sessions() as session:
        await ai.set_binding(
            session, purpose="p", scope=None, connection_id=connection_id, model="m"
        )
        await session.commit()
    await get_then_delete.deleting
    async with sessions() as session:
        [binding] = list(await session.scalars(select(Binding)))
    assert (binding.model, binding.connection_id) == ("m", None)
