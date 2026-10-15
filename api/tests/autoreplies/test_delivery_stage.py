"""Где выдача сейчас: этап двигают обработчики вместе с журналом, для вкладок «Выдач»."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app import autoreplies, instagram
from app.autoreplies.models import Autoreply, Delivery
from app.instagram.models import Account

AT = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


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


async def report(session, delivery, stage, outcome="sent", variant=None) -> None:
    await autoreplies.handle_send_result(
        session,
        instagram.OutboxResult(
            f"autoreplies:{delivery.id}:{stage}", "message", outcome, None, AT, variant
        ),
    )
    await session.commit()


async def click(session, delivery) -> None:
    await autoreplies.handle_postback(
        session,
        instagram.PostbackRef(
            account_id=delivery.account_id,
            person_id="p1",
            payload=f"ar:{delivery.id}",
            mid=str(uuid.uuid4()),
            acted_at=AT,
            received_at=AT,
        ),
    )
    await session.commit()


async def stage(session, delivery) -> str:
    await session.refresh(delivery)
    return delivery.stage


async def test_new_delivery_is_sending(session, delivery):
    assert await stage(session, delivery) == "sending"


async def test_happy_path(session, delivery):
    await report(session, delivery, "intro")
    assert await stage(session, delivery) == "waiting_click"
    await click(session, delivery)
    assert await stage(session, delivery) == "clicked"
    await report(session, delivery, "material")
    assert await stage(session, delivery) == "delivered"


async def test_follow_round(session, delivery):
    await report(session, delivery, "intro")
    await click(session, delivery)
    await report(session, delivery, "material", variant=instagram.NOT_FOLLOWING)
    assert await stage(session, delivery) == "follow_asked"
    # подписался и нажал снова: материал снова в очереди
    await click(session, delivery)
    assert await stage(session, delivery) == "clicked"


@pytest.mark.parametrize(
    ("sent", "want"), [("intro", "dm_failed"), ("material", "material_failed")]
)
async def test_failures(session, delivery, sent, want):
    await report(session, delivery, sent, outcome="failed")
    assert await stage(session, delivery) == want


async def test_click_after_failed_material_starts_over(session, delivery):
    await report(session, delivery, "material", outcome="failed")
    await click(session, delivery)
    assert await stage(session, delivery) == "clicked"


@pytest.mark.parametrize("outcome", ["sent", "failed"])
async def test_comment_reply_does_not_move(session, delivery, outcome):
    # ответ под комментом вежливость, а не выдача
    await report(session, delivery, "intro")
    await report(session, delivery, "comment", outcome=outcome)
    assert await stage(session, delivery) == "waiting_click"


async def test_delivered_is_final(session, delivery):
    await report(session, delivery, "material")
    # запоздалый отчёт прошлого раунда и нажатие после выдачи этап не откатят
    await report(session, delivery, "material", outcome="failed")
    await click(session, delivery)
    assert await stage(session, delivery) == "delivered"


async def test_unknown_stage_rejected(session, delivery):
    delivery.stage = "maybe"
    with pytest.raises(IntegrityError):
        await session.commit()
