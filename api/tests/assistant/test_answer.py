"""Цикл ответа: взять коммент, спросить нейросеть, записать решение. Нейросеть
подменена: настоящий агент ассистента на FunctionModel, сеть не нужна."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select

from app import ai, assistant
from app.activity.models import Event
from app.assistant.models import Assistant, Reply
from app.instagram.models import Account, OutboxTask


@pytest.fixture
def make_session(session):
    @asynccontextmanager
    async def same():
        yield session

    return same


@pytest.fixture
async def account(session) -> Account:
    account = Account(
        ig_user_id="17841400000000000",
        username="altai.tours",
        token_encrypted="x",
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()
    return account


async def add_assistant(session, account, **kw) -> Assistant:
    a = Assistant(
        **{
            "account_id": account.id,
            "name": "Все вопросы",
            "scope": "all",
            "mode": "direct",
            "daily_limit": 200,
            "knowledge": "С собакой: на Алтай нельзя.",
            "created_by": uuid.uuid7(),
        }
        | kw
    )
    session.add(a)
    await session.commit()
    return a


async def add_reply(session, a: Assistant, **kw) -> Reply:
    reply = Reply(
        **{
            "assistant_id": a.id,
            "account_id": a.account_id,
            "comment_id": f"c-{uuid.uuid4()}",
            "media_id": "m1",
            "person_id": "p1",
            "comment_text": "А с собакой можно?",
            "commented_at": datetime.now(UTC),
            "run_at": datetime.now(UTC) - timedelta(seconds=1),
        }
        | kw
    )
    session.add(reply)
    await session.commit()
    return reply


class Brain:
    """Подменённый ai.run: прогоняет агента ассистента на FunctionModel."""

    def __init__(self, monkeypatch):
        self.calls: list[dict] = []
        self.answer = {
            "decision": "answer",
            "direct": "Нельзя.",
            "comment": "Нельзя, подробно в директе",
            "source": "С собакой",
        }
        self.fail: str | None = None
        self.during = None
        monkeypatch.setattr(ai, "run", self.run)

    async def run(self, *, purpose, scope, agent, prompt, make_session, **kw):
        self.calls.append({"purpose": purpose, "scope": scope, "prompt": prompt})
        if self.during:
            await self.during()
        if self.fail:
            raise ai.AiCallFailed(self.fail)

        def model(messages, info: AgentInfo):
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, self.answer)])

        return await agent.run(prompt, model=FunctionModel(model))


@pytest.fixture
def brain(monkeypatch):
    return Brain(monkeypatch)


async def fresh(session, row):
    await session.refresh(row)
    return row


async def outbox(session) -> list[OutboxTask]:
    return list(await session.scalars(select(OutboxTask)))


async def journal(session) -> list[str]:
    return [e.kind for e in await session.scalars(select(Event).order_by(Event.occurred_at))]


async def test_empty_queue(make_session, brain):
    assert await assistant.answer_once(make_session) is False
    assert brain.calls == []


@pytest.mark.parametrize(
    ("mode", "kind", "text", "part"),
    [
        ("direct", "private_reply", "Нельзя.", "direct"),
        ("comment", "comment_reply", "Нельзя, подробно в директе", "comment"),
        # combo начинает с директа: коммент встанет, когда директ уйдёт
        ("combo", "private_reply", "Нельзя.", "direct"),
    ],
)
async def test_answer_goes_to_outbox(session, make_session, brain, account, mode, kind, text, part):
    a = await add_assistant(session, account, mode=mode)
    reply = await add_reply(session, a)
    assert await assistant.answer_once(make_session) is True
    [call] = brain.calls
    assert (call["purpose"], call["scope"]) == ("assistant.answer", str(a.id))
    assert "А с собакой можно?" in call["prompt"]
    reply = await fresh(session, reply)
    assert (reply.stage, reply.outcome, reply.source) == ("sending", "answered", "С собакой")
    assert (reply.taken_at is not None, reply.attempts) == (True, 1)
    [task] = await outbox(session)
    assert (task.kind, task.payload["text"], task.ref) == (
        kind,
        text,
        f"assistant:{reply.id}:{part}",
    )
    assert await journal(session) == ["assistant.answered"]


@pytest.mark.parametrize("decision", ["unsure", "not_mine"])
async def test_silence(session, make_session, brain, account, decision):
    a = await add_assistant(session, account)
    reply = await add_reply(session, a)
    brain.answer = {"decision": decision}
    await assistant.answer_once(make_session)
    reply = await fresh(session, reply)
    assert (reply.stage, reply.outcome) == ("done", decision)
    assert await outbox(session) == []
    assert await journal(session) == [f"assistant.{decision}"]


@pytest.mark.parametrize("state", ["paused", "archived"])
async def test_paused_before_take(session, make_session, brain, account, state):
    kw = {"enabled": False} if state == "paused" else {"archived_at": datetime.now(UTC)}
    a = await add_assistant(session, account, **kw)
    reply = await add_reply(session, a)
    await assistant.answer_once(make_session)
    assert brain.calls == []
    assert ((await fresh(session, reply)).outcome, await outbox(session)) == ("paused", [])


async def test_paused_while_thinking(session, make_session, brain, account):
    # владелец поставил на паузу, пока нейросеть писала ответ: ответ не уходит
    a = await add_assistant(session, account)
    reply = await add_reply(session, a)

    async def pause():
        a.enabled = False
        await session.commit()

    brain.during = pause
    await assistant.answer_once(make_session)
    reply = await fresh(session, reply)
    assert (reply.stage, reply.outcome) == ("done", "paused")
    assert await outbox(session) == []


async def test_too_old(session, make_session, brain, account):
    a = await add_assistant(session, account)
    reply = await add_reply(session, a, commented_at=datetime.now(UTC) - timedelta(hours=25))
    await assistant.answer_once(make_session)
    assert brain.calls == []
    assert (await fresh(session, reply)).outcome == "expired"


async def test_daily_limit(session, make_session, brain, account):
    a = await add_assistant(session, account, daily_limit=1)
    now = datetime.now(UTC)
    # прочитан сегодня, даже промолчав: в предел считается
    await add_reply(session, a, stage="done", outcome="not_mine", taken_at=now)
    # прочитан вчера по UTC: не считается
    yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    await add_reply(session, a, stage="done", outcome="answered", taken_at=yesterday)
    reply = await add_reply(session, a)
    await assistant.answer_once(make_session)
    assert brain.calls == []
    reply = await fresh(session, reply)
    # упёрся в предел: в счётчик не попадает, taken_at пустой
    assert (reply.outcome, reply.taken_at) == ("limit", None)


async def test_transient_failure_retried_then_failed(session, make_session, brain, account):
    a = await add_assistant(session, account)
    reply = await add_reply(session, a)
    brain.fail = "timeout"
    delays = []
    for _ in range(2):
        before = datetime.now(UTC)
        await assistant.answer_once(make_session)
        reply = await fresh(session, reply)
        assert (reply.stage, reply.error_code) == ("queued", "timeout")
        delays.append(reply.run_at - before)
        # не ждём паузу: делаем вид, что время пришло
        reply.run_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert delays[0] >= timedelta(seconds=59) and delays[1] >= timedelta(minutes=4, seconds=59)
    await assistant.answer_once(make_session)
    reply = await fresh(session, reply)
    assert (reply.stage, reply.outcome, reply.attempts) == ("done", "failed", 3)
    assert await journal(session) == ["assistant.failed"]


@pytest.mark.parametrize("code", ["key_rejected", "no_funds", "not_configured", "model_missing"])
async def test_permanent_failure_not_retried(session, make_session, brain, account, code):
    a = await add_assistant(session, account)
    reply = await add_reply(session, a)
    brain.fail = code
    await assistant.answer_once(make_session)
    reply = await fresh(session, reply)
    assert (reply.stage, reply.outcome, reply.error_code) == ("done", "failed", code)


async def test_stuck_released_and_retaken(session, make_session, brain, account):
    # worker упал посреди запроса: строка висит в thinking
    a = await add_assistant(session, account)
    stuck = datetime.now(UTC) - timedelta(minutes=6)
    reply = await add_reply(session, a, stage="thinking", taken_at=stuck, attempts=1)
    await assistant.answer_once(make_session)
    reply = await fresh(session, reply)
    assert (reply.stage, reply.outcome, reply.attempts) == ("sending", "answered", 2)


async def test_stuck_too_often_fails(session, make_session, brain, account):
    a = await add_assistant(session, account)
    stuck = datetime.now(UTC) - timedelta(minutes=6)
    reply = await add_reply(session, a, stage="thinking", taken_at=stuck, attempts=3)
    await assistant.answer_once(make_session)
    assert brain.calls == []
    reply = await fresh(session, reply)
    assert (reply.outcome, reply.error_code) == ("failed", "stuck")


async def test_late_result_of_released_run_dropped(session, make_session, brain, account):
    # пока этот запуск думал, строку сочли брошенной и взяли заново: его итог
    # не должен лечь поверх нового запуска
    a = await add_assistant(session, account)
    reply = await add_reply(session, a)

    async def retaken():
        reply.taken_at = datetime.now(UTC) + timedelta(seconds=1)
        await session.commit()

    brain.during = retaken
    await assistant.answer_once(make_session)
    reply = await fresh(session, reply)
    assert (reply.stage, reply.outcome) == ("thinking", None)
    assert await outbox(session) == []


async def test_one_person_at_a_time(session, make_session, brain, account):
    # другой коммент этого человека сейчас у нейросети: этот подождёт
    a = await add_assistant(session, account)
    await add_reply(session, a, stage="thinking", taken_at=datetime.now(UTC))
    waiting = await add_reply(session, a)
    assert await assistant.answer_once(make_session) is True
    assert brain.calls == []
    waiting = await fresh(session, waiting)
    assert waiting.stage == "queued" and waiting.run_at > datetime.now(UTC)


async def test_already_replied(session, make_session, brain, account):
    # на этот коммент Private Reply уже стоит: второе письмо Meta не примет
    a = await add_assistant(session, account)
    reply = await add_reply(session, a)
    session.add(
        OutboxTask(
            account_id=account.id,
            kind="private_reply",
            payload={"comment_id": reply.comment_id, "text": "раньше"},
            dedup_key=f"private_reply:{reply.comment_id}",
        )
    )
    await session.commit()
    await assistant.answer_once(make_session)
    reply = await fresh(session, reply)
    assert (reply.stage, reply.error_code) == ("send_failed", "already_replied")
