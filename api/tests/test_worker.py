"""Круг worker: разбирает входящие пачкой не больше BATCH, каждое в своей сессии."""

import uuid
from contextlib import asynccontextmanager

from sqlalchemy import func, select

from app import worker
from app.instagram import webhook
from app.instagram.models import InboxEvent


def sessions(session):
    """Фабрика сессий для круга: отдаёт песочницу теста и не закрывает её."""

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
    assert await worker.run_once(sessions(session)) == 0


async def test_handles_all_waiting(session):
    await add_events(session, 3)
    assert await worker.run_once(sessions(session)) == 3
    assert await pending(session) == 0


async def test_stops_at_batch(session):
    await add_events(session, worker.BATCH + 2)
    assert await worker.run_once(sessions(session)) == worker.BATCH
    assert await pending(session) == 2


def test_nobody_gets_events_yet():
    # автоответов ещё нет; появятся, и здесь будет autoreplies.handle_comment
    assert worker.HANDLERS.on_comment is None
