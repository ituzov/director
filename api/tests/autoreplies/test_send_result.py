"""Итог отправки письма автоответа: этап в выдаче и запись в журнал."""

import uuid

import pytest
from sqlalchemy import select

from app import autoreplies, instagram
from app.activity.models import Event
from app.autoreplies.models import Autoreply, Delivery


@pytest.fixture
async def delivery(session) -> Delivery:
    autoreply = Autoreply(
        account_id=uuid.uuid7(),
        name="Гайд",
        scope="all",
        intro_text="Держи",
        button_text="Получить",
        reply_text="ссылка",
        created_by=uuid.uuid7(),
    )
    session.add(autoreply)
    await session.flush()
    delivery = Delivery(
        autoreply_id=autoreply.id,
        account_id=autoreply.account_id,
        comment_id="c1",
        media_id="m1",
        person_id="p1",
        keyword="гайд",
    )
    session.add(delivery)
    await session.commit()
    return delivery


async def report(session, ref: str, kind="private_reply", outcome="sent", reason=None) -> None:
    await autoreplies.handle_send_result(
        session, instagram.OutboxResult(ref, kind, outcome, reason)
    )
    await session.commit()


async def journal(session) -> list[Event]:
    return list(await session.scalars(select(Event)))


async def test_intro_sent(session, delivery):
    await report(session, f"autoreplies:{delivery.id}:intro")
    await session.refresh(delivery)
    assert (delivery.sent_at is not None, delivery.commented_at) == (True, None)
    [entry] = await journal(session)
    assert (entry.kind, entry.autoreply_id, entry.person_id, entry.comment_id) == (
        "autoreply.sent",
        delivery.autoreply_id,
        "p1",
        "c1",
    )
    assert entry.data == {"delivery_id": str(delivery.id), "stage": "intro"}


async def test_comment_sent(session, delivery):
    await report(session, f"autoreplies:{delivery.id}:comment", kind="comment_reply")
    await session.refresh(delivery)
    assert (delivery.commented_at is not None, delivery.sent_at) == (True, None)
    assert [e.kind for e in await journal(session)] == ["autoreply.commented"]


async def test_material_sent(session, delivery):
    await report(session, f"autoreplies:{delivery.id}:material", kind="message")
    await session.refresh(delivery)
    assert delivery.delivered_at is not None
    assert [e.kind for e in await journal(session)] == ["autoreply.delivered"]


@pytest.mark.parametrize(("outcome", "reason"), [("failed", "100"), ("expired", None)])
async def test_not_sent(session, delivery, outcome, reason):
    await report(session, f"autoreplies:{delivery.id}:intro", outcome=outcome, reason=reason)
    await session.refresh(delivery)
    assert delivery.sent_at is None
    [entry] = await journal(session)
    assert entry.kind == "autoreply.send_failed"
    assert entry.data == {
        "delivery_id": str(delivery.id),
        "stage": "intro",
        "outcome": outcome,
        "reason": reason,
    }


@pytest.mark.parametrize(
    "ref",
    [
        "assistant:1:intro",
        # чужой модуль с номером, совпавшим с нашей выдачей: всё равно не наше
        "assistant:{id}:intro",
        "autoreplies:not-a-uuid:intro",
        "autoreplies",
        "autoreplies:{id}",
        f"autoreplies:{uuid.uuid7()}:intro",
        "autoreplies:{id}:unknown",
    ],
)
async def test_foreign_or_unknown_ignored(session, delivery, ref):
    await report(session, ref.format(id=delivery.id))
    await session.refresh(delivery)
    assert delivery.sent_at is None
    assert await journal(session) == []
