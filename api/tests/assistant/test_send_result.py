"""Итог отправки письма ассистента: стадия ответа, журнал, коммент после директа
в режиме «кратко + директ». Чужие метки и повторы отчёта ничего не меняют."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import assistant, instagram
from app.activity.models import Event
from app.assistant.models import Assistant, Reply
from app.instagram.models import Account, OutboxTask

FINISHED = datetime(2026, 10, 17, 12, 5, tzinfo=UTC)


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


async def sending(session, account, mode) -> Reply:
    a = Assistant(
        account_id=account.id,
        name="Все вопросы",
        scope="all",
        mode=mode,
        daily_limit=200,
        created_by=uuid.uuid7(),
    )
    session.add(a)
    await session.flush()
    reply = Reply(
        assistant_id=a.id,
        account_id=account.id,
        comment_id="c1",
        media_id="m1",
        person_id="p1",
        comment_text="?",
        commented_at=FINISHED,
        stage="sending",
        outcome="answered",
        direct_reply="Нельзя." if mode in ("direct", "combo") else None,
        comment_reply="Нельзя, подробно в директе" if mode in ("comment", "combo") else None,
    )
    session.add(reply)
    await session.commit()
    return reply


async def report(session, reply, part, outcome="sent", reason=None):
    result = instagram.OutboxResult(
        ref=f"assistant:{reply.id}:{part}",
        kind="private_reply" if part == "direct" else "comment_reply",
        outcome=outcome,
        reason=reason,
        finished_at=FINISHED,
    )
    await assistant.handle_send_result(session, result)
    await session.commit()
    await session.refresh(reply)


async def comments(session) -> list[OutboxTask]:
    return list(await session.scalars(select(OutboxTask).where(OutboxTask.kind == "comment_reply")))


async def journal(session) -> list[tuple[str, str]]:
    events = await session.scalars(select(Event).order_by(Event.occurred_at, Event.id))
    return [(e.kind, e.data["part"]) for e in events]


@pytest.mark.parametrize(("mode", "part"), [("direct", "direct"), ("comment", "comment")])
async def test_sent(session, account, mode, part):
    reply = await sending(session, account, mode)
    await report(session, reply, part)
    assert reply.stage == "sent"
    assert await journal(session) == [("assistant.sent", part)]
    # коммент после отправки ставит только combo
    assert await comments(session) == []


@pytest.mark.parametrize(("mode", "part"), [("direct", "direct"), ("comment", "comment")])
async def test_send_failed(session, account, mode, part):
    # коммент удалили или окно Private Reply закрылось
    reply = await sending(session, account, mode)
    await report(session, reply, part, outcome="failed", reason="10")
    assert (reply.stage, reply.error_code) == ("send_failed", "10")
    assert await journal(session) == [("assistant.send_failed", part)]


async def test_combo_comment_after_direct(session, account):
    reply = await sending(session, account, "combo")
    assert await comments(session) == []
    await report(session, reply, "direct")
    # директ ушёл: теперь коммент «подробно в директе» правда
    assert reply.stage == "sent"
    [task] = await comments(session)
    assert (task.payload["text"], task.ref) == (
        "Нельзя, подробно в директе",
        f"assistant:{reply.id}:comment",
    )


async def test_combo_no_comment_when_direct_failed(session, account):
    # директ не ушёл: коммент пообещал бы то, чего нет
    reply = await sending(session, account, "combo")
    await report(session, reply, "direct", outcome="expired")
    assert (reply.stage, reply.error_code) == ("send_failed", "expired")
    assert await comments(session) == []


async def test_combo_comment_result_only_in_journal(session, account):
    reply = await sending(session, account, "combo")
    await report(session, reply, "direct")
    await report(session, reply, "comment", outcome="failed", reason="100")
    # строку решил директ, он у человека; коммент не ушёл, это видно в журнале
    assert (reply.stage, reply.error_code) == ("sent", None)
    assert await journal(session) == [
        ("assistant.sent", "direct"),
        ("assistant.send_failed", "comment"),
    ]


async def test_repeated_report(session, account):
    # отчёт пришёл дважды: второго коммента нет, стадия та же
    reply = await sending(session, account, "combo")
    await report(session, reply, "direct")
    await report(session, reply, "direct", outcome="failed")
    assert reply.stage == "sent"
    assert len(await comments(session)) == 1


@pytest.mark.parametrize(
    "ref",
    [
        "autoreplies:01a1:intro",
        "assistant:not-a-uuid:direct",
        "assistant:{id}:other",
        f"assistant:{uuid.uuid7()}:direct",
    ],
    ids=["foreign", "bad-id", "bad-part", "no-reply"],
)
async def test_not_ours(session, account, ref):
    reply = await sending(session, account, "direct")
    result = instagram.OutboxResult(
        ref=ref.format(id=reply.id),
        kind="private_reply",
        outcome="sent",
        reason=None,
        finished_at=FINISHED,
    )
    await assistant.handle_send_result(session, result)
    await session.commit()
    await session.refresh(reply)
    assert reply.stage == "sending"
    assert await journal(session) == []
