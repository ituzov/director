"""Чтение журнала по комментам: только свой аккаунт и свои комменты, по порядку."""

import uuid
from datetime import UTC, datetime, timedelta

from app import activity
from app.activity.models import Event

T0 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
ACCOUNT = uuid.uuid7()


def add(session, kind, comment_id, *, minute=0, account_id=ACCOUNT, **kw) -> None:
    activity.record(
        session,
        kind,
        account_id=account_id,
        comment_id=comment_id,
        occurred_at=T0 + timedelta(minutes=minute),
        **kw,
    )


async def history(session, *comment_ids, account_id=ACCOUNT):
    return await activity.comment_history(session, account_id, list(comment_ids))


async def test_events_of_comments_in_order(session):
    guide = uuid.uuid7()
    # записаны не по порядку: порядок держит время, а не вставка
    add(session, "autoreply.sent", "c1", minute=2, autoreply_id=guide)
    add(session, "comment.received", "c1", minute=1, data={"text": "гайд"})
    add(session, "autoreply.clicked", "c2", minute=3, autoreply_id=guide)
    await session.commit()

    events = await history(session, "c1", "c2")
    got = [(e.kind, e.comment_id, e.autoreply_id, e.data) for e in events]
    assert got == [
        ("comment.received", "c1", None, {"text": "гайд"}),
        ("autoreply.sent", "c1", guide, {}),
        ("autoreply.clicked", "c2", guide, {}),
    ]


async def test_same_time_by_id(session):
    # одна транзакция пишет несколько событий с одним временем: порядок записи по id.
    # Вставляем от больших id к меньшим, иначе порядок вставки совпал бы с ответом
    kinds = ["autoreply.matched", "autoreply.sent", "autoreply.commented"]
    ids = sorted(uuid.uuid7() for _ in kinds)
    for event_id, kind in reversed(list(zip(ids, kinds, strict=True))):
        session.add(
            Event(id=event_id, kind=kind, account_id=ACCOUNT, comment_id="c1", occurred_at=T0)
        )
        await session.flush()
    await session.commit()
    assert [e.kind for e in await history(session, "c1")] == kinds


async def test_only_asked_comments(session):
    add(session, "comment.received", "c1")
    add(session, "comment.received", "c2")
    await session.commit()
    assert [e.comment_id for e in await history(session, "c1")] == ["c1"]


async def test_only_own_account(session):
    # id коммента пишет Meta: тот же id в чужом аккаунте не наш
    add(session, "comment.received", "c1", account_id=uuid.uuid7())
    await session.commit()
    assert await history(session, "c1") == []


async def test_no_comments_no_query(session, monkeypatch):
    async def boom(*args):
        raise AssertionError("запрос без комментов")

    monkeypatch.setattr("app.activity.repository.comment_events", boom)
    assert await history(session) == []
