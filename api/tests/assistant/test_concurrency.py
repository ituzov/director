"""Замки assistant на настоящих соединениях: песочница одного соединения их не
покажет. Настоящие коммиты, после теста уборка."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app import ai, assistant
from app.ai.models import Connection
from app.assistant import service
from app.assistant.exceptions import AssistantConflict
from app.assistant.models import Assistant, Reply
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
                "ai.binding, ai.connection, instagram.outbox, instagram.account, "
                "activity.event CASCADE"
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


@pytest.fixture
def slow_brain(monkeypatch):
    """ai.run, который думает заметное время: оба цикла успевают взять своё."""
    calls = []

    async def run(*, agent, prompt, **kw):
        calls.append(prompt)
        await asyncio.sleep(0.3)

        def model(messages, info: AgentInfo):
            args = {"decision": "answer", "direct": "Нельзя."}
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

        return await agent.run(prompt, model=FunctionModel(model))

    monkeypatch.setattr(ai, "run", run)
    return calls


async def queue(sessions, account_id, *, daily_limit=200, people=("p1", "p2")):
    async with sessions() as session:
        a = Assistant(
            account_id=account_id,
            name="Все вопросы",
            scope="all",
            mode="direct",
            daily_limit=daily_limit,
            created_by=uuid.uuid7(),
        )
        session.add(a)
        await session.flush()
        past = datetime.now(UTC) - timedelta(seconds=1)
        session.add_all(
            Reply(
                assistant_id=a.id,
                account_id=account_id,
                comment_id=f"c{n}",
                media_id="m1",
                person_id=person,
                comment_text="?",
                commented_at=past,
                run_at=past,
            )
            for n, person in enumerate(people)
        )
        await session.commit()


async def outcomes(sessions) -> list[str | None]:
    async with sessions() as session:
        return sorted(str(r.outcome) for r in await session.scalars(select(Reply)))


async def test_limit_not_passed_by_two_loops(sessions, setup, slow_brain):
    # предел 1, два цикла разом: нейросеть спросят один раз, второй упрётся в предел
    account_id, _ = setup
    await queue(sessions, account_id, daily_limit=1)
    await asyncio.gather(assistant.answer_once(sessions), assistant.answer_once(sessions))
    assert len(slow_brain) == 1
    assert await outcomes(sessions) == ["answered", "limit"]


async def test_one_person_not_answered_twice_at_once(sessions, setup, slow_brain):
    # два коммента одного человека: пока первый у нейросети, второй ждёт
    account_id, _ = setup
    await queue(sessions, account_id, people=("p1", "p1"))
    await asyncio.gather(assistant.answer_once(sessions), assistant.answer_once(sessions))
    assert len(slow_brain) == 1
    assert await outcomes(sessions) == ["None", "answered"]
