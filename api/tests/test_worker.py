"""Циклы worker: одно событие за раз, каждое в своей сессии; остановка по сигналу."""

import asyncio
import uuid
from contextlib import asynccontextmanager

import httpx
from sqlalchemy import func, select

from app import autoreplies, instagram, worker
from app.core import crypto
from app.instagram import tasks, webhook
from app.instagram.models import Account, InboxEvent


def sessions(session):
    """Фабрика сессий для цикла: отдаёт песочницу теста и не закрывает её."""

    @asynccontextmanager
    async def make():
        yield session

    return make


async def add_events(session, count: int) -> None:
    for _ in range(count):
        session.add(
            InboxEvent(
                ig_account_id="0",
                kind=webhook.COMMENT,
                dedup_key=f"comment:{uuid.uuid4()}",
                payload={},
            )
        )
    await session.commit()


async def pending(session) -> int:
    return await session.scalar(
        select(func.count()).select_from(InboxEvent).where(InboxEvent.processed_at.is_(None))
    )


async def test_nothing_to_do(session):
    assert await worker.inbox_once(sessions(session)) is False
    assert await worker.outbox_once(sessions(session)) is False


async def test_one_event_at_a_time(session):
    await add_events(session, 2)
    assert await worker.inbox_once(sessions(session)) is True
    assert await pending(session) == 1
    assert await worker.inbox_once(sessions(session)) is True
    assert await pending(session) == 0
    assert await worker.inbox_once(sessions(session)) is False


def test_comments_go_to_autoreplies():
    assert worker.HANDLERS.on_comment is autoreplies.handle_comment
    assert worker.HANDLERS.on_postback is autoreplies.handle_postback
    assert worker.ON_RESULT is autoreplies.handle_send_result


async def test_outbox_once_sends(session, monkeypatch):
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted=crypto.encrypt("t"),
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.flush()
    await instagram.enqueue_comment_reply(session, account_id=account.id, comment_id="c1", text="x")
    await session.commit()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "r1"}))
    monkeypatch.setattr(tasks, "_http", lambda: httpx.AsyncClient(transport=transport))

    assert await worker.outbox_once(sessions(session)) is True
    assert await worker.outbox_once(sessions(session)) is False


async def test_loop_works_while_busy_and_stops(monkeypatch):
    # пока работа есть, без пауз: пауза в минуту здесь сорвала бы таймаут.
    # Сигнал пришёл во время события: выходим сразу после него
    monkeypatch.setattr(worker, "POLL_SECONDS", 60)
    stop = asyncio.Event()
    calls = []

    async def once():
        calls.append(1)
        if len(calls) == 3:
            stop.set()
        return True

    await asyncio.wait_for(worker.run_loop("test", once, stop), 1)
    assert len(calls) == 3


async def test_loop_survives_errors(monkeypatch):
    # база недоступна: цикл не падает, а пробует снова
    monkeypatch.setattr(worker, "POLL_SECONDS", 0)
    stop = asyncio.Event()
    calls = []

    async def once():
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("db down")
        stop.set()
        return True

    await asyncio.wait_for(worker.run_loop("test", once, stop), 1)
    assert len(calls) == 2


async def test_sleep_wakes_on_stop(monkeypatch):
    # пустая очередь и долгий сон, но SIGTERM будит сразу
    monkeypatch.setattr(worker, "POLL_SECONDS", 60)
    stop = asyncio.Event()

    async def idle():
        return False

    task = asyncio.create_task(worker.run_loop("test", idle, stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 1)
