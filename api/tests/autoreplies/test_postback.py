"""Нажатие кнопки автоответа: материал один раз, двойной тап и повторы не шлют второй."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import autoreplies, instagram
from app.activity.models import Event
from app.autoreplies.models import Autoreply, Delivery
from app.instagram.models import Account, OutboxTask

CLICK = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture
async def delivery(session) -> Delivery:
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted="x",
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.flush()
    autoreply = Autoreply(
        account_id=account.id,
        name="Гайд",
        scope="all",
        intro_text="Держи",
        button_text="Получить",
        reply_text="https://guide",
        created_by=uuid.uuid7(),
    )
    session.add(autoreply)
    await session.flush()
    delivery = Delivery(
        autoreply_id=autoreply.id,
        account_id=account.id,
        comment_id="c1",
        media_id="m1",
        person_id="p1",
        keyword="гайд",
    )
    session.add(delivery)
    await session.commit()
    return delivery


def click(delivery, *, at=CLICK, person_id="p1", mid=None, payload=None) -> instagram.PostbackRef:
    return instagram.PostbackRef(
        account_id=delivery.account_id,
        person_id=person_id,
        payload=payload if payload is not None else f"ar:{delivery.id}",
        mid=mid or str(uuid.uuid4()),
        acted_at=at,
    )


async def press(session, postback) -> bool:
    taken = await autoreplies.handle_postback(session, postback)
    await session.commit()
    return taken


async def outbox(session) -> list[OutboxTask]:
    return list(await session.scalars(select(OutboxTask)))


async def journal(session) -> list[str]:
    return [e.kind for e in await session.scalars(select(Event).order_by(Event.id))]


async def test_click_queues_material(session, delivery):
    assert await press(session, click(delivery)) is True
    [task] = await outbox(session)
    assert (task.kind, task.ref, task.dedup_key) == (
        "message",
        f"autoreplies:{delivery.id}:material",
        f"message:material:{delivery.id}",
    )
    assert task.payload == {"recipient_id": "p1", "text": "https://guide"}
    # окно 24 часа от нажатия
    assert task.expires_at == CLICK + timedelta(hours=24)
    await session.refresh(delivery)
    assert (delivery.clicked_at, delivery.last_click_at) == (CLICK, CLICK)
    assert await journal(session) == ["autoreply.clicked"]


async def test_double_tap_ignored(session, delivery):
    await press(session, click(delivery))
    await press(session, click(delivery, at=CLICK + timedelta(seconds=5)))
    assert len(await outbox(session)) == 1
    assert await journal(session) == ["autoreply.clicked"]


async def test_second_click_while_material_queued(session, delivery):
    await press(session, click(delivery))
    # через минуту, материал ещё не ушёл: второй в очередь не ляжет
    await press(session, click(delivery, at=CLICK + timedelta(minutes=1)))
    assert len(await outbox(session)) == 1
    await session.refresh(delivery)
    assert delivery.clicked_at == CLICK
    assert delivery.last_click_at == CLICK + timedelta(minutes=1)


async def test_click_after_delivered_ignored(session, delivery):
    delivery.delivered_at = CLICK
    delivery.last_click_at = CLICK
    await session.commit()
    await press(session, click(delivery, at=CLICK + timedelta(hours=1)))
    assert await outbox(session) == []
    assert await journal(session) == ["autoreply.repeat_click"]


async def test_archived_autoreply_still_delivers(session, delivery):
    autoreply = await session.get(Autoreply, delivery.autoreply_id)
    autoreply.enabled, autoreply.archived_at = False, CLICK
    await session.commit()
    await press(session, click(delivery))
    assert len(await outbox(session)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"person_id": "p2"},
        {"payload": f"ar:{uuid.uuid7()}"},
        {"payload": "ar:not-a-uuid"},
    ],
)
async def test_foreign_click_ignored(session, delivery, change):
    assert await press(session, click(delivery, **change)) is True
    assert await outbox(session) == []
    assert await journal(session) == []


async def test_other_button_not_ours(session, delivery):
    assert await press(session, click(delivery, payload="assistant:1")) is False
    assert await outbox(session) == []


async def test_other_account_ignored(session, delivery):
    postback = click(delivery)
    postback = instagram.PostbackRef(
        account_id=uuid.uuid7(),
        person_id=postback.person_id,
        payload=postback.payload,
        mid=postback.mid,
        acted_at=postback.acted_at,
    )
    await press(session, postback)
    assert await outbox(session) == []
