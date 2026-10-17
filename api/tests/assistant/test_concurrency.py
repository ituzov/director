"""Замки assistant на настоящих соединениях: песочница одного соединения их не
покажет. Настоящие коммиты, после теста уборка."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.ai.models import Connection
from app.assistant import service
from app.assistant.exceptions import AssistantConflict
from app.assistant.schemas import AssistantIn
from app.core import crypto
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
                "TRUNCATE assistant.reply, assistant.assistant_media, assistant.assistant, "
                "ai.binding, ai.connection, instagram.account CASCADE"
            )
        )
    await engine.dispose()


@pytest.fixture
async def setup(sessions):
    async with sessions() as session:
        account = Account(
            ig_user_id="17841400000000001",
            username="altai.tours",
            token_encrypted="x",
            connected_by=uuid.uuid7(),
        )
        connection = Connection(
            provider="timeweb",
            name="Таймвеб",
            key_encrypted=crypto.encrypt("sk-test-key-0123456789"),
            key_hint="6789",
            key_changed_at=datetime.now(UTC),
            created_by=uuid.uuid7(),
        )
        session.add_all([account, connection])
        await session.commit()
        return account.id, connection.id


def form(account_id, connection_id, **kw) -> AssistantIn:
    return AssistantIn(
        **{
            "account_id": account_id,
            "name": "Все вопросы",
            "scope": "all",
            "mode": "direct",
            "daily_limit": 200,
            "connection_id": connection_id,
            "model": "m",
        }
        | kw
    )


async def save(sessions, body):
    async with sessions() as session:
        try:
            await service.create(session, body, OWNER)
            return "created"
        except AssistantConflict as conflict:
            return conflict.kind


@pytest.mark.parametrize(
    "kw",
    [{}, {"scope": "posts", "media_ids": ["m1"]}],
    ids=["general", "same-post"],
)
async def test_two_tabs_save_at_once(sessions, setup, kw):
    # две вкладки разом: одна сохраняется, вторая получает понятный конфликт,
    # а не 500 от уникального индекса
    account_id, connection_id = setup
    results = await asyncio.gather(
        save(sessions, form(account_id, connection_id, name="Первый", **kw)),
        save(sessions, form(account_id, connection_id, name="Второй", **kw)),
    )
    assert sorted(results) == sorted(["created", "general" if not kw else "post"])
