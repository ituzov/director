"""Запись в журнал: идёт в транзакции вызывающего, форму вида события держат код и база."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import activity
from app.activity.models import Event


async def events(session) -> list[Event]:
    return list(await session.scalars(select(Event)))


async def test_recorded_with_commit(session):
    account_id = uuid.uuid7()
    activity.record(
        session,
        "comment.received",
        account_id=account_id,
        person_id="940112315461736",
        comment_id="18000000000000000",
        data={"text": "гайд"},
    )
    await session.commit()

    [event] = await events(session)
    assert (event.kind, event.account_id, event.person_id) == (
        "comment.received",
        account_id,
        "940112315461736",
    )
    assert event.data == {"text": "гайд"}
    assert event.occurred_at is not None


async def test_occurred_at_given(session):
    # коммент написали раньше, чем worker до него добрался: в журнале время коммента
    written = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    activity.record(session, "comment.received", occurred_at=written)
    await session.commit()
    [event] = await events(session)
    assert event.occurred_at == written


async def test_data_defaults_to_empty(session):
    activity.record(session, "meta_app.updated")
    await session.commit()
    [event] = await events(session)
    assert event.data == {}


async def test_rolled_back_with_caller(session):
    # действие сорвалось: запись о нём не должна остаться
    activity.record(session, "comment.received")
    await session.rollback()
    assert await events(session) == []


@pytest.mark.parametrize("kind", ["CommentReceived", "comment", "comment.received.twice", ""])
def test_bad_kind_rejected_in_code(session, kind):
    with pytest.raises(ValueError, match="модуль.действие"):
        activity.record(session, kind)


async def test_bad_kind_rejected_by_database(session):
    # в обход record: последняя страховка в базе
    session.add(Event(kind="CommentReceived", data={}))
    with pytest.raises(IntegrityError, match="ck_event_kind_format"):
        await session.commit()


async def test_long_external_ids_fit(session):
    # длину id человека и коммента Meta не обещает: длинные ложатся
    activity.record(session, "comment.received", person_id="1" * 100, comment_id="2" * 100)
    await session.commit()
