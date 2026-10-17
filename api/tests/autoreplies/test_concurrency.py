"""Замки autoreplies на настоящих соединениях: песочница одного соединения их не
покажет. Настоящие коммиты, после теста уборка."""

import asyncio
import contextlib
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.autoreplies import repository, service
from app.autoreplies.exceptions import AutoreplyArchived
from app.autoreplies.models import Autoreply, AutoreplyMedia
from app.autoreplies.schemas import AutoreplyForm, AutoreplyIn
from app.db import make_engine
from app.identity import UserRef
from app.instagram.models import Account
from tests.conftest import TEST_DATABASE_URL

OWNER = UserRef(id=uuid.uuid7(), role="owner", can_connect_accounts=True)


@pytest.fixture
async def sessions():
    engine = make_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE autoreplies.keyword, autoreplies.autoreply_media, "
                "autoreplies.delivery, autoreplies.autoreply, instagram.account CASCADE"
            )
        )
    await engine.dispose()


async def test_archive_and_save_at_once(sessions, monkeypatch):
    # вкладка A сохраняет форму, вкладка B отправляет автоответ в архив. Если архив
    # успел между чтением и записью формы, архивный не должен остаться с живыми постами
    async with sessions() as session:
        account = Account(
            ig_user_id="17841400000000002",
            username="shop",
            token_encrypted="x",
            connected_by=uuid.uuid7(),
        )
        session.add(account)
        await session.commit()
        body = AutoreplyIn(
            account_id=account.id,
            name="Гайд",
            scope="posts",
            media_ids=["m1"],
            keywords=["гайд"],
            intro_text="Держи",
            button_text="Получить",
            reply_text="ссылка",
        )
        created = (await service.create(session, body, OWNER)).autoreply.id

    read = repository.get_autoreply
    archived = asyncio.Event()

    async def read_then_archive(session, autoreply_id):
        found = await read(session, autoreply_id)
        if not archived.is_set():
            archived.set()

            async def archive():
                async with sessions() as other:
                    await service.archive(other, autoreply_id)

            task = asyncio.create_task(archive())
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), 0.5)
            read_then_archive.task = task
        return found

    monkeypatch.setattr(repository, "get_autoreply", read_then_archive)
    async with sessions() as session:
        with contextlib.suppress(AutoreplyArchived):
            await service.update(
                session, created, AutoreplyForm(**body.model_dump(exclude={"account_id"}))
            )
    await read_then_archive.task
    async with sessions() as session:
        a = await session.get(Autoreply, created)
        media = list(await session.scalars(select(AutoreplyMedia.archived)))
    assert a.archived_at is not None
    assert media == [True]
