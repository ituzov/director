"""Шаги выдачи по комментам для ленты входящих: коды вместо событий журнала,
наружу только нужные подробности."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import activity, autoreplies, instagram
from app.autoreplies.models import Autoreply, Delivery
from app.instagram.models import Account

T0 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


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


def journal(session, delivery, kind, comment_id="c1", *, minute=0, account_id=None, data=None):
    activity.record(
        session,
        kind,
        account_id=account_id or delivery.account_id,
        autoreply_id=delivery.autoreply_id,
        person_id="p1",
        comment_id=comment_id,
        data=data,
        occurred_at=T0 + timedelta(minutes=minute),
    )


async def report(
    session, delivery, stage, outcome="sent", reason=None, variant=None, *, minute=0
) -> None:
    await autoreplies.handle_send_result(
        session,
        instagram.OutboxResult(
            f"autoreplies:{delivery.id}:{stage}",
            "message",
            outcome,
            reason,
            T0 + timedelta(minutes=minute),
            variant,
        ),
    )
    await session.commit()


async def history(client, owner, account_id, *comment_ids) -> dict:
    r = await client.get(
        "/autoreplies/history",
        headers=owner,
        params={"account_id": str(account_id), "comment_id": list(comment_ids)},
    )
    assert r.status_code == 200, r.text
    return r.json()["comments"]


def steps(comments, comment_id="c1") -> list[str]:
    return [s["step"] for s in comments[comment_id]]


async def test_chain_from_handlers(client, session, owner, delivery):
    # записи делают настоящие обработчики: чтение не разойдётся с записью
    journal(session, delivery, "autoreply.matched", data={"keyword": "гайд", "delivery_id": "x"})
    await session.commit()
    await report(session, delivery, "intro")
    await report(session, delivery, "comment")
    await autoreplies.handle_postback(
        session,
        instagram.PostbackRef(
            account_id=delivery.account_id,
            person_id="p1",
            payload=f"ar:{delivery.id}",
            mid="m1",
            acted_at=datetime.now(UTC),
        ),
    )
    await session.commit()
    await report(session, delivery, "material", variant="unknown")

    got = {s["step"]: s for s in (await history(client, owner, delivery.account_id, "c1"))["c1"]}
    assert set(got) == {"matched", "dm_sent", "commented", "clicked", "delivered"}
    assert got["matched"]["keyword"] == "гайд"
    assert got["delivered"]["follow"] == "unknown"
    assert {s["autoreply_id"] for s in got.values()} == {str(delivery.autoreply_id)}
    # внутренности автоответов наружу не уходят
    assert set(got["matched"]) == {
        "step",
        "at",
        "autoreply_id",
        "keyword",
        "outcome",
        "reason",
        "follow",
    }


async def test_late_report_keeps_order(client, session, owner, delivery):
    # директ ушёл в 12:00, человек нажал в 12:01, а отчёт об отправке дошёл после
    # нажатия (упал и повторился): в цепочке директ всё равно раньше нажатия
    await autoreplies.handle_postback(
        session,
        instagram.PostbackRef(
            account_id=delivery.account_id,
            person_id="p1",
            payload=f"ar:{delivery.id}",
            mid="m1",
            acted_at=T0 + timedelta(minutes=1),
        ),
    )
    await session.commit()
    await report(session, delivery, "intro")
    assert steps(await history(client, owner, delivery.account_id, "c1")) == [
        "dm_sent",
        "clicked",
    ]


async def test_failures_by_stage(client, session, owner, delivery):
    await report(session, delivery, "intro", outcome="failed", reason="551")
    await report(session, delivery, "comment", outcome="expired", reason="window")
    await report(session, delivery, "material", outcome="failed", reason="10")

    comments = await history(client, owner, delivery.account_id, "c1")
    got = [(s["step"], s["outcome"], s["reason"]) for s in comments["c1"]]
    assert sorted(got) == sorted(
        [
            ("dm_failed", "failed", "551"),
            ("comment_failed", "expired", "window"),
            ("material_failed", "failed", "10"),
        ]
    )


async def test_failure_without_details_kept(client, session, owner, delivery):
    # подробности стёрли: этапа нет, но неудача из цепочки не пропадает
    journal(session, delivery, "autoreply.send_failed")
    await session.commit()
    assert steps(await history(client, owner, delivery.account_id, "c1")) == ["send_failed"]


async def test_steps_in_order_by_comment(client, session, owner, delivery):
    journal(session, delivery, "autoreply.clicked", minute=1)
    journal(session, delivery, "autoreply.follow_asked", minute=2)
    journal(session, delivery, "autoreply.repeat_click", minute=3)
    # повторный коммент записан под своим id: у его строки один шаг
    journal(session, delivery, "autoreply.repeat_comment", "c2", minute=4)
    await session.commit()

    comments = await history(client, owner, delivery.account_id, "c1", "c2")
    assert steps(comments) == ["clicked", "follow_asked", "repeat_click"]
    assert steps(comments, "c2") == ["repeat_comment"]


async def test_foreign_events_skipped(client, session, owner, delivery):
    # коммент записал instagram: строка ленты и есть он, шагом автоответа он не стал
    journal(session, delivery, "comment.received")
    journal(session, delivery, "autoreply.unknown_kind")
    await session.commit()
    assert await history(client, owner, delivery.account_id, "c1") == {}


async def test_only_own_account(client, session, owner, delivery):
    journal(session, delivery, "autoreply.matched", account_id=uuid.uuid7())
    await session.commit()
    assert await history(client, owner, delivery.account_id, "c1") == {}


async def test_needs_login(client, delivery):
    r = await client.get(
        "/autoreplies/history",
        params={"account_id": str(delivery.account_id), "comment_id": "c1"},
    )
    assert r.status_code == 401


@pytest.mark.parametrize(("count", "code"), [(0, 422), (100, 200), (101, 422)])
async def test_comment_limit(client, owner, count, code):
    params = {"account_id": str(uuid.uuid7()), "comment_id": [f"c{n}" for n in range(count)]}
    r = await client.get("/autoreplies/history", headers=owner, params=params)
    assert r.status_code == code, r.text
