"""Шаг worker: одно входящее за раз, в своей сессии."""

import uuid
from contextlib import asynccontextmanager

from sqlalchemy import func, select

from app import worker
from app.instagram import webhook
from app.instagram.models import InboxEvent


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


def test_nobody_gets_events_yet():
    # автоответов ещё нет; появятся, и здесь будет autoreplies.handle_comment
    assert worker.HANDLERS.on_comment is None
