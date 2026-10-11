"""Шаг worker: одно входящее за раз, в своей сессии."""

import uuid
from contextlib import asynccontextmanager

import httpx
from sqlalchemy import func, select

from app import autoreplies, instagram, worker
from app.core import crypto
from app.instagram import tasks, webhook
from app.instagram.models import Account, InboxEvent


def sessions(session):
    """Фабрика сессий для шага: отдаёт песочницу теста и не закрывает её."""

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
    assert await worker.step(sessions(session)) is False


async def test_one_event_per_step(session):
    await add_events(session, 2)
    assert await worker.step(sessions(session)) is True
    assert await pending(session) == 1
    assert await worker.step(sessions(session)) is True
    assert await pending(session) == 0
    assert await worker.step(sessions(session)) is False


def test_comments_go_to_autoreplies():
    assert worker.HANDLERS.on_comment is autoreplies.handle_comment
    assert worker.ON_RESULT is autoreplies.handle_send_result


async def test_step_sends_outbox(session, monkeypatch):
    # входящих нет, а исходящее есть: шаг занят, не спим
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

    assert await worker.step(sessions(session)) is True
    assert await worker.step(sessions(session)) is False
