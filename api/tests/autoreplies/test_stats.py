"""Сводка для обзора: воронка выдач аккаунта за период, топ автоответов и отправки,
которые не ушли. Считается прямо по выдачам и outbox."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.autoreplies.models import Autoreply, Delivery
from app.instagram.models import Account, OutboxTask

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=10)
# самая свежая выдача: её время карточка покажет как «последний раз»
LATEST = NOW + timedelta(minutes=1)


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


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


async def autoreply(session, account_id, name) -> Autoreply:
    autoreply = Autoreply(
        account_id=account_id,
        name=name,
        scope="all",
        intro_text="Держи",
        button_text="Получить",
        reply_text="ссылка",
        created_by=uuid.uuid7(),
    )
    session.add(autoreply)
    await session.flush()
    return autoreply


def delivery(autoreply, *, created_at=NOW, sent=False, clicked=False, delivered=False):
    return Delivery(
        autoreply_id=autoreply.id,
        account_id=autoreply.account_id,
        comment_id=str(uuid.uuid7()),
        media_id="m1",
        person_id=str(uuid.uuid7()),
        keyword="гайд",
        created_at=created_at,
        sent_at=NOW if sent else None,
        clicked_at=NOW if clicked else None,
        delivered_at=NOW if delivered else None,
    )


def task(account, *, outcome, ref="autoreplies:x:intro", finished_at=NOW):
    return OutboxTask(
        account_id=account.id,
        kind="private_reply",
        payload={},
        ref=ref,
        dedup_key=str(uuid.uuid7()),
        outcome=outcome,
        finished_at=finished_at,
    )


async def stats(client, owner, account, **params):
    return await client.get(
        "/autoreplies/stats", headers=owner, params={"account_id": str(account.id), **params}
    )


async def test_funnel_and_top(client, owner, account, session):
    guide = await autoreply(session, account.id, "Гайд")
    price = await autoreply(session, account.id, "Прайс")
    other = await autoreply(session, uuid.uuid7(), "Чужой")
    session.add_all(
        [
            delivery(guide, sent=True, clicked=True, delivered=True),
            delivery(guide, created_at=LATEST, sent=True, clicked=True),
            delivery(guide, sent=True),
            delivery(guide),
            delivery(price, sent=True, clicked=True, delivered=True),
            # старше периода и чужой аккаунт не считаются
            delivery(guide, created_at=OLD, sent=True, clicked=True, delivered=True),
            delivery(other, sent=True, clicked=True, delivered=True),
        ]
    )
    await session.commit()

    r = await stats(client, owner, account)
    assert r.status_code == 200
    body = r.json()
    assert (body["triggered"], body["sent"], body["clicked"], body["delivered"]) == (5, 4, 3, 2)
    assert [(t["name"], t["triggered"], t["delivered"]) for t in body["top"]] == [
        ("Гайд", 4, 1),
        ("Прайс", 1, 1),
    ]
    assert body["top"][0]["id"] == str(guide.id)
    # карточкам те же цифры и когда сработал последний раз; старая выдача не в счёт
    assert body["by_autoreply"] == body["top"]
    assert datetime.fromisoformat(body["by_autoreply"][0]["last_at"]) == LATEST


async def test_period(client, owner, account, session):
    guide = await autoreply(session, account.id, "Гайд")
    session.add_all([delivery(guide), delivery(guide, created_at=OLD)])
    await session.commit()
    assert (await stats(client, owner, account, days=30)).json()["triggered"] == 2


async def test_top_five(client, owner, account, session):
    for i in range(6):
        a = await autoreply(session, account.id, f"Автоответ {i}")
        session.add_all([delivery(a) for _ in range(i + 1)])
    await session.commit()
    body = (await stats(client, owner, account)).json()
    assert [t["triggered"] for t in body["top"]] == [6, 5, 4, 3, 2]
    # карточкам нужны все, а не только пятёрка
    assert [t["triggered"] for t in body["by_autoreply"]] == [6, 5, 4, 3, 2, 1]


async def test_undelivered(client, owner, account, session):
    session.add_all(
        [
            task(account, outcome="failed"),
            task(account, outcome="expired", ref="autoreplies:y:material"),
            task(account, outcome="sent"),
            # чужая метка и давняя не считаются
            task(account, outcome="failed", ref="assistant:z"),
            task(account, outcome="failed", finished_at=OLD),
        ]
    )
    await session.commit()
    assert (await stats(client, owner, account)).json()["undelivered"] == 2


async def test_empty(client, owner, account):
    assert (await stats(client, owner, account)).json() == {
        "triggered": 0,
        "sent": 0,
        "clicked": 0,
        "delivered": 0,
        "undelivered": 0,
        "top": [],
        "by_autoreply": [],
    }


@pytest.mark.parametrize("days", [0, 91])
async def test_days_bounds(client, owner, account, days):
    assert (await stats(client, owner, account, days=days)).status_code == 422


async def test_anonymous_rejected(client, account):
    r = await client.get("/autoreplies/stats", params={"account_id": str(account.id)})
    assert r.status_code == 401
