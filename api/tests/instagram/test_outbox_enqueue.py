"""Постановка исходящих: задача ложится в транзакции вызывающего, повтор не дублирует,
срок считается от действия человека, request_id вебхука едет с задачей."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import instagram
from app.instagram.models import Account, OutboxTask

AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture
async def account(session) -> Account:
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted="x",
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()
    return account


async def tasks(session) -> list[OutboxTask]:
    return list(await session.scalars(select(OutboxTask).order_by(OutboxTask.id)))


async def test_private_reply_with_button(session, account):
    added = await instagram.enqueue_private_reply(
        session,
        account_id=account.id,
        comment_id="c1",
        commented_at=AT,
        text="Держи 👇",
        button=instagram.Button(title="Получить", payload="ar:1"),
        ref="autoreplies:1",
    )
    await session.commit()
    assert added is True
    [task] = await tasks(session)
    assert (task.kind, task.ref, task.dedup_key) == (
        "private_reply",
        "autoreplies:1",
        "private_reply:c1",
    )
    assert task.payload == {
        "comment_id": "c1",
        "text": "Держи 👇",
        "button": {"title": "Получить", "payload": "ar:1"},
    }
    # Meta принимает Private Reply 7 дней от коммента
    assert task.expires_at == AT + timedelta(days=7)
    assert (task.outcome, task.attempts) == (None, 0)


async def test_one_private_reply_per_comment(session, account):
    args = {"account_id": account.id, "comment_id": "c1", "commented_at": AT, "text": "x"}
    assert await instagram.enqueue_private_reply(session, **args) is True
    assert await instagram.enqueue_private_reply(session, **args | {"text": "y"}) is False
    await session.commit()
    [task] = await tasks(session)
    assert task.payload["text"] == "x"


async def test_message_window_and_dedup(session, account):
    args = {
        "account_id": account.id,
        "recipient_id": "p1",
        "acted_at": AT,
        "text": "ссылка",
        "dedup_key": "click:1",
    }
    assert await instagram.enqueue_message(session, **args) is True
    assert await instagram.enqueue_message(session, **args) is False
    await session.commit()
    [task] = await tasks(session)
    assert task.payload == {"recipient_id": "p1", "text": "ссылка"}
    assert task.expires_at == AT + timedelta(hours=24)


async def test_comment_reply_never_expires(session, account):
    await instagram.enqueue_comment_reply(
        session, account_id=account.id, comment_id="c1", text="Отправили!"
    )
    await session.commit()
    [task] = await tasks(session)
    assert (task.kind, task.expires_at, task.payload) == (
        "comment_reply",
        None,
        {"comment_id": "c1", "text": "Отправили!"},
    )


async def test_private_reply_and_comment_reply_are_separate(session, account):
    await instagram.enqueue_private_reply(
        session, account_id=account.id, comment_id="c1", commented_at=AT, text="x"
    )
    await instagram.enqueue_comment_reply(session, account_id=account.id, comment_id="c1", text="y")
    await session.commit()
    assert [t.kind for t in await tasks(session)] == ["private_reply", "comment_reply"]


async def test_rolled_back_with_caller(session, account):
    await instagram.enqueue_comment_reply(session, account_id=account.id, comment_id="c1", text="y")
    await session.rollback()
    assert await tasks(session) == []


async def test_request_id_travels(session, account):
    with structlog.contextvars.bound_contextvars(request_id="req-1"):
        await instagram.enqueue_comment_reply(
            session, account_id=account.id, comment_id="c1", text="y"
        )
    await session.commit()
    [task] = await tasks(session)
    assert task.request_id == "req-1"


def make_task(account, **kw) -> OutboxTask:
    return OutboxTask(
        **{"account_id": account.id, "kind": "message", "payload": {}, "dedup_key": "k"} | kw
    )


async def test_unknown_kind_rejected(session, account):
    session.add(make_task(account, kind="email"))
    with pytest.raises(IntegrityError, match="ck_outbox_kind_known"):
        await session.commit()


async def test_unknown_outcome_rejected(session, account):
    session.add(make_task(account, outcome="maybe", finished_at=AT))
    with pytest.raises(IntegrityError, match="ck_outbox_outcome_known"):
        await session.commit()


@pytest.mark.parametrize("fields", [{"outcome": "sent"}, {"finished_at": AT}])
async def test_outcome_only_when_finished(session, account, fields):
    session.add(make_task(account, **fields))
    with pytest.raises(IntegrityError, match="ck_outbox_outcome_when_finished"):
        await session.commit()


async def test_message_with_follow_check(session, account):
    await instagram.enqueue_message(
        session,
        account_id=account.id,
        recipient_id="p1",
        acted_at=AT,
        text="ссылка",
        dedup_key="d1:0",
        if_not_following=("Подпишись", instagram.Button(title="Получить", payload="ar:1")),
    )
    await session.commit()
    [task] = await tasks(session)
    assert task.payload == {
        "recipient_id": "p1",
        "text": "ссылка",
        "not_following": {
            "text": "Подпишись",
            "button": {"title": "Получить", "payload": "ar:1"},
        },
        "if_unknown": "following",
    }
