"""Несколько отправителей разом: одно письмо уходит один раз, лимит Private Reply
в час не превышается. Песочница одного соединения этого не покажет, поэтому здесь
настоящие соединения и коммиты, а после теста уборка."""

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app import instagram, worker
from app.core import crypto
from app.db import make_engine
from app.instagram import repository, tasks
from app.instagram.models import Account, OutboxTask
from app.instagram.tasks import PRIVATE_REPLIES_PER_HOUR
from tests.conftest import TEST_DATABASE_URL


@pytest.fixture
async def sessions():
    engine = make_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE instagram.outbox, instagram.account CASCADE"))
    await engine.dispose()


class SlowMeta:
    """Meta отвечает не сразу: оба отправителя успевают взять задачу одновременно."""

    def __init__(self) -> None:
        self.comments: list[str] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.comments.append(request.url.path)
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"id": "r", "message_id": "m"})


@pytest.fixture
def meta(monkeypatch) -> SlowMeta:
    fake = SlowMeta()
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(tasks, "_http", lambda: httpx.AsyncClient(transport=transport))
    return fake


async def make_account(sessions) -> uuid.UUID:
    async with sessions() as session:
        account = Account(
            ig_user_id="17841400000000000",
            username="shop",
            token_encrypted=crypto.encrypt("t"),
            connected_by=uuid.uuid7(),
        )
        session.add(account)
        await session.commit()
        return account.id


async def outcomes(sessions, kind: str) -> list[str | None]:
    async with sessions() as session:
        rows = await session.scalars(select(OutboxTask.outcome).where(OutboxTask.kind == kind))
        return list(rows)


async def test_senders_take_different_tasks(sessions, meta, monkeypatch):
    account_id = await make_account(sessions)
    async with sessions() as session:
        for comment in ("c1", "c2"):
            await instagram.enqueue_comment_reply(
                session, account_id=account_id, comment_id=comment, text="x"
            )
        await session.commit()

    # забрав задачу, отправитель ждёт, пока заберёт и второй: гонка неизбежна.
    # Без SKIP LOCKED второй застрял бы на чужой задаче, без блокировки взял бы её же
    barrier = asyncio.Barrier(2)
    claim = repository.claim_outbox_task

    async def claim_then_wait(session):
        task = await claim(session)
        await barrier.wait()
        return task

    monkeypatch.setattr(repository, "claim_outbox_task", claim_then_wait)
    results = await asyncio.wait_for(
        asyncio.gather(worker.outbox_once(sessions), worker.outbox_once(sessions)), 3
    )
    assert results == [True, True]
    assert sorted(meta.comments) == sorted(
        [f"/{tasks.graph.VERSION}/c1/replies", f"/{tasks.graph.VERSION}/c2/replies"]
    )
    assert await outcomes(sessions, "comment_reply") == ["sent", "sent"]


async def test_hour_limit_holds_with_two_senders(sessions, meta):
    account_id = await make_account(sessions)
    now = datetime.now(UTC)
    async with sessions() as session:
        # за час уже отправлено на одно меньше лимита
        session.add_all(
            OutboxTask(
                account_id=account_id,
                kind="private_reply",
                payload={},
                dedup_key=f"sent:{i}",
                outcome="sent",
                finished_at=now,
            )
            for i in range(PRIVATE_REPLIES_PER_HOUR - 1)
        )
        for comment in ("c1", "c2"):
            await instagram.enqueue_private_reply(
                session, account_id=account_id, comment_id=comment, commented_at=now, text="x"
            )
        await session.commit()

    await asyncio.gather(worker.outbox_once(sessions), worker.outbox_once(sessions))
    # ушло ровно одно, второе перенесено на следующий час, а не отправлено сверх лимита
    assert len(meta.comments) == 1
    assert (await outcomes(sessions, "private_reply")).count(None) == 1
