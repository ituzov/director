"""Где выдача сейчас: этап двигают обработчики вместе с журналом, для вкладок «Выдач».
Этап двигает только событие не старше текущего: отчёт об отправке может опоздать."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app import autoreplies, instagram
from app.autoreplies.models import Autoreply, Delivery
from app.instagram.models import Account

T0 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


def at(minute: int) -> datetime:
    return T0 + timedelta(minutes=minute)


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
        # коммент пришёл в 12:00, всё дальше по минутам
        stage_at=T0,
    )
    session.add(delivery)
    await session.commit()
    return delivery


async def report(session, delivery, stage, minute, outcome="sent", variant=None) -> None:
    await autoreplies.handle_send_result(
        session,
        instagram.OutboxResult(
            f"autoreplies:{delivery.id}:{stage}", "message", outcome, None, at(minute), variant
        ),
    )
    await session.commit()


async def click(session, delivery, minute) -> None:
    await autoreplies.handle_postback(
        session,
        instagram.PostbackRef(
            account_id=delivery.account_id,
            person_id="p1",
            payload=f"ar:{delivery.id}",
            mid=str(uuid.uuid4()),
            acted_at=at(minute),
            received_at=at(minute),
        ),
    )
    await session.commit()


async def stage(session, delivery) -> str:
    await session.refresh(delivery)
    return delivery.stage


async def test_new_delivery_is_sending(session, delivery):
    assert await stage(session, delivery) == "sending"


async def test_happy_path(session, delivery):
    await report(session, delivery, "intro", 1)
    assert await stage(session, delivery) == "waiting_click"
    await click(session, delivery, 2)
    assert await stage(session, delivery) == "clicked"
    await report(session, delivery, "material", 3)
    assert await stage(session, delivery) == "delivered"


async def test_follow_round(session, delivery):
    await report(session, delivery, "intro", 1)
    await click(session, delivery, 2)
    await report(session, delivery, "material", 3, variant=instagram.NOT_FOLLOWING)
    assert await stage(session, delivery) == "follow_asked"
    # подписался и нажал снова: материал снова в очереди
    await click(session, delivery, 4)
    assert await stage(session, delivery) == "clicked"


@pytest.mark.parametrize(
    ("sent", "want"), [("intro", "dm_failed"), ("material", "material_failed")]
)
async def test_failures(session, delivery, sent, want):
    await report(session, delivery, sent, 1, outcome="failed")
    assert await stage(session, delivery) == want


async def test_click_after_failed_material_starts_over(session, delivery):
    await report(session, delivery, "material", 1, outcome="failed")
    await click(session, delivery, 2)
    assert await stage(session, delivery) == "clicked"


@pytest.mark.parametrize("outcome", ["sent", "failed"])
@pytest.mark.parametrize("before", ["clicked", "follow_asked"])
async def test_comment_reply_does_not_move(session, delivery, outcome, before):
    # ответ под комментом вежливость, а не выдача: этап не трогает, когда бы ни пришёл
    await report(session, delivery, "intro", 1)
    await click(session, delivery, 2)
    if before == "follow_asked":
        await report(session, delivery, "material", 3, variant=instagram.NOT_FOLLOWING)
    await report(session, delivery, "comment", 4, outcome=outcome)
    assert await stage(session, delivery) == before


@pytest.mark.parametrize(
    ("after", "want"),
    [("click", "clicked"), ("follow", "follow_asked"), ("lost", "material_failed")],
)
async def test_late_intro_report_does_not_roll_back(session, delivery, after, want):
    # директ ушёл в 12:01, а отчёт о нём упал и повторился уже после того, что было дальше
    await click(session, delivery, 2)
    if after == "follow":
        await report(session, delivery, "material", 3, variant=instagram.NOT_FOLLOWING)
    if after == "lost":
        await report(session, delivery, "material", 3, outcome="failed")
    await report(session, delivery, "intro", 1)
    assert await stage(session, delivery) == want


async def test_late_follow_report_after_new_click(session, delivery):
    # просьба подписаться ушла в 12:03, человек подписался и нажал в 12:04, а отчёт
    # о просьбе дошёл только теперь: он не вернёт в «ждём подписку»
    await report(session, delivery, "intro", 1)
    await click(session, delivery, 2)
    await click(session, delivery, 4)
    await report(session, delivery, "material", 3, variant=instagram.NOT_FOLLOWING)
    assert await stage(session, delivery) == "clicked"


async def test_late_delivered_report_after_new_click(session, delivery):
    # материал ушёл в 12:03, отчёт упал; человек нажал ещё раз в 12:04, а отчёт о
    # выдаче дошёл после нажатия: материал у человека, цепочка закрыта
    await report(session, delivery, "intro", 1)
    await click(session, delivery, 2)
    await click(session, delivery, 4)
    await report(session, delivery, "material", 3)
    assert await stage(session, delivery) == "delivered"
    assert delivery.delivered_at is not None


async def test_delivered_is_final(session, delivery):
    await report(session, delivery, "material", 1)
    # отчёт другого раунда и нажатие после выдачи этап не откатят, даже если новее
    await report(session, delivery, "material", 2, outcome="failed")
    await click(session, delivery, 3)
    assert await stage(session, delivery) == "delivered"


async def test_unknown_stage_rejected(session, delivery):
    delivery.stage = "maybe"
    with pytest.raises(IntegrityError):
        await session.commit()
