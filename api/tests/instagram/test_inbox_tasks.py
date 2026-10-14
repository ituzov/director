"""Разбор входящих worker: одно событие в транзакции, итог и причина у каждого,
упавшее повторяется с паузой и после пяти попыток сдаётся."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import instagram
from app.activity.models import Event
from app.instagram import webhook
from app.instagram.models import Account, InboxEvent

IG_ID = "17841400000000000"
RECEIVED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
NOBODY = instagram.InboxHandlers()


def comment_payload(**kw) -> dict:
    return {
        "id": "180001",
        "text": "хочу гайд",
        "from": {"id": "500001", "username": "vasya"},
        "media": {"id": "190001", "media_product_type": "FEED"},
    } | kw


@pytest.fixture
async def account(session) -> Account:
    account = Account(
        ig_user_id=IG_ID, username="shop", token_encrypted="x", connected_by=uuid.uuid7()
    )
    session.add(account)
    await session.commit()
    return account


async def add_event(session, *, kind=webhook.COMMENT, payload=None, ig_id=IG_ID, **kw) -> uuid.UUID:
    event = InboxEvent(
        **{
            "ig_account_id": ig_id,
            "kind": kind,
            "dedup_key": f"{kind}:{uuid.uuid4()}",
            "payload": comment_payload() if payload is None else payload,
            "received_at": RECEIVED,
        }
        | kw
    )
    session.add(event)
    await session.commit()
    return event.id


async def stored(session, event_id) -> InboxEvent:
    return await session.get(InboxEvent, event_id, populate_existing=True)


async def journal(session) -> list[Event]:
    return list(await session.scalars(select(Event)))


async def test_nothing_to_do(session):
    assert await instagram.process_inbox_event(session, NOBODY) is False


async def test_comment_goes_to_journal_and_handler(session, account):
    event_id = await add_event(session)
    got = []

    async def on_comment(s, comment):
        got.append(comment)
        return "autoreplies"

    handlers = instagram.InboxHandlers(on_comment=on_comment)
    assert await instagram.process_inbox_event(session, handlers) is True

    [comment] = got
    assert comment == instagram.CommentRef(
        account_id=account.id,
        comment_id="180001",
        media_id="190001",
        person_id="500001",
        username="vasya",
        text="хочу гайд",
        received_at=RECEIVED,
    )
    event = await stored(session, event_id)
    assert (event.outcome, event.reason, event.processed_at is not None) == ("done", None, True)
    # кто взял, видно в ленте входящих
    assert event.handled_by == "autoreplies"
    [entry] = await journal(session)
    assert (entry.kind, entry.account_id, entry.person_id, entry.comment_id) == (
        "comment.received",
        account.id,
        "500001",
        "180001",
    )
    # время коммента, а не разбора
    assert entry.occurred_at == RECEIVED
    assert entry.data == {"text": "хочу гайд", "media_id": "190001", "username": "vasya"}


async def test_comment_nobody_took_still_done(session, account):
    # ни один автоответ не подошёл: разобрано, просто никто не взял
    event_id = await add_event(session)

    async def not_mine(s, comment):
        return None

    await instagram.process_inbox_event(session, instagram.InboxHandlers(on_comment=not_mine))
    event = await stored(session, event_id)
    assert (event.outcome, event.reason, event.handled_by) == ("done", None, None)


async def test_comment_without_handler_still_journaled(session, account):
    event_id = await add_event(session)
    await instagram.process_inbox_event(session, NOBODY)
    assert (await stored(session, event_id)).outcome == "done"
    assert [e.kind for e in await journal(session)] == ["comment.received"]


async def test_oldest_first(session, account):
    late = await add_event(session, received_at=RECEIVED + timedelta(seconds=1))
    early = await add_event(session)
    await instagram.process_inbox_event(session, NOBODY)
    assert (await stored(session, early)).outcome == "done"
    assert (await stored(session, late)).outcome is None


async def test_unknown_account_skipped(session):
    # тестовый вебхук из кабинета Meta приходит с аккаунтом 0
    event_id = await add_event(session, ig_id="0")
    await instagram.process_inbox_event(session, NOBODY)
    event = await stored(session, event_id)
    assert (event.outcome, event.reason, event.handled_by) == ("skipped", "unknown_account", None)
    assert await journal(session) == []


async def test_inactive_account_skipped(session, account):
    account.status, account.token_encrypted = "disconnected", None
    await session.commit()
    event_id = await add_event(session)
    await instagram.process_inbox_event(session, NOBODY)
    event = await stored(session, event_id)
    assert (event.outcome, event.reason, event.handled_by) == ("skipped", "account_inactive", None)


async def test_own_comment_skipped(session, account):
    event_id = await add_event(session, payload=comment_payload(**{"from": {"id": IG_ID}}))
    await instagram.process_inbox_event(session, NOBODY)
    event = await stored(session, event_id)
    assert (event.outcome, event.reason, event.handled_by) == ("skipped", "own_comment", None)
    assert await journal(session) == []


@pytest.mark.parametrize(
    "payload",
    [
        comment_payload(text=None),
        comment_payload(**{"from": {}}),
        comment_payload(**{"from": "500001"}),
        comment_payload(media=None),
        {"id": "180001"},
    ],
)
async def test_bad_comment_skipped(session, account, payload):
    event_id = await add_event(session, payload=payload)
    await instagram.process_inbox_event(session, NOBODY)
    event = await stored(session, event_id)
    assert (event.outcome, event.reason) == ("skipped", "bad_payload")


@pytest.mark.parametrize("kind", [webhook.MESSAGE, webhook.READ])
async def test_other_kinds_done_without_journal(session, account, kind):
    event_id = await add_event(session, kind=kind, payload={"sender": {"id": "500001"}})
    await instagram.process_inbox_event(session, NOBODY)
    assert (await stored(session, event_id)).outcome == "done"
    assert await journal(session) == []


def postback_payload(**kw) -> dict:
    return {
        "sender": {"id": "500001"},
        "recipient": {"id": IG_ID},
        # нажали за 2 с до того, как Meta прислала вебхук (RECEIVED)
        "timestamp": 1767323043000,
        "postback": {"mid": "pb-1", "title": "Получить", "payload": "ar:123"},
    } | kw


async def test_postback_goes_to_handler(session, account):
    event_id = await add_event(session, kind=webhook.POSTBACK, payload=postback_payload())
    got = []

    async def on_postback(s, postback):
        got.append(postback)
        return "autoreplies"

    await instagram.process_inbox_event(session, instagram.InboxHandlers(on_postback=on_postback))
    assert got == [
        instagram.PostbackRef(
            account_id=account.id,
            person_id="500001",
            payload="ar:123",
            mid="pb-1",
            # время нажатия по часам Meta, а не время вебхука
            acted_at=RECEIVED - timedelta(seconds=2),
        )
    ]
    event = await stored(session, event_id)
    assert (event.outcome, event.handled_by) == ("done", "autoreplies")


async def test_postback_without_timestamp_uses_received(session, account):
    payload = postback_payload()
    del payload["timestamp"]
    await add_event(session, kind=webhook.POSTBACK, payload=payload)
    got = []

    async def on_postback(s, postback):
        got.append(postback)
        return "autoreplies"

    await instagram.process_inbox_event(session, instagram.InboxHandlers(on_postback=on_postback))
    assert got[0].acted_at == RECEIVED


@pytest.mark.parametrize(
    "payload",
    [
        postback_payload(sender={}),
        postback_payload(postback={"mid": "pb-1"}),
        postback_payload(postback={"payload": "ar:1"}),
        {"sender": {"id": "1"}},
    ],
)
async def test_bad_postback_skipped(session, account, payload):
    event_id = await add_event(session, kind=webhook.POSTBACK, payload=payload)
    await instagram.process_inbox_event(session, NOBODY)
    event = await stored(session, event_id)
    assert (event.outcome, event.reason) == ("skipped", "bad_payload")


async def test_postback_without_handler_done(session, account):
    event_id = await add_event(session, kind=webhook.POSTBACK, payload=postback_payload())
    await instagram.process_inbox_event(session, NOBODY)
    assert (await stored(session, event_id)).outcome == "done"


async def failing(session, comment):
    raise RuntimeError("boom")


async def test_failure_rolls_back_and_schedules_retry(session, account):
    event_id = await add_event(session)
    handlers = instagram.InboxHandlers(on_comment=failing)
    assert await instagram.process_inbox_event(session, handlers) is True

    event = await stored(session, event_id)
    assert (event.processed_at, event.outcome) == (None, None)
    assert (event.attempts, event.reason) == (1, "RuntimeError")
    assert event.retry_at is not None
    # comment.received откатился вместе с упавшим обработчиком
    assert await journal(session) == []
    # пауза ещё не прошла: событие не берётся
    assert await instagram.process_inbox_event(session, NOBODY) is False


async def test_retry_taken_when_due(session, account):
    event_id = await add_event(session, attempts=1, retry_at=RECEIVED)
    await instagram.process_inbox_event(session, NOBODY)
    event = await stored(session, event_id)
    assert (event.outcome, event.retry_at) == ("done", None)


async def test_fifth_failure_gives_up(session, account):
    event_id = await add_event(session, attempts=4, retry_at=RECEIVED)
    await instagram.process_inbox_event(session, instagram.InboxHandlers(on_comment=failing))
    event = await stored(session, event_id)
    assert (event.outcome, event.reason, event.attempts) == ("failed", "RuntimeError", 5)
    # сдались: никто не взял, даже если обработчик успел что-то сделать до падения
    assert (event.processed_at is not None, event.handled_by) == (True, None)
    assert await instagram.process_inbox_event(session, NOBODY) is False


async def test_logs_carry_request_id_not_text(session, account, real_logging, capsys):
    await add_event(session, request_id="req-1")
    real_logging()
    capsys.readouterr()
    await instagram.process_inbox_event(session, instagram.InboxHandlers(on_comment=failing))
    out = capsys.readouterr().err
    lines = [json.loads(line) for line in out.splitlines()]
    [retry] = [e for e in lines if e["event"] == "inbox.retry"]
    assert retry["request_id"] == "req-1"
    # текст коммента в лог не идёт, даже когда разбор упал
    assert "хочу гайд" not in out
