"""«Выдачи»: выдачи аккаунта страницами по этапам, ник и текст коммента из входящих,
счётчики этапов для вкладок."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.autoreplies.models import Autoreply, Delivery
from app.instagram import webhook
from app.instagram.models import Account, InboxEvent

T0 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
IG_ID = "17841400000000000"


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


@pytest.fixture
async def account(session) -> Account:
    account = Account(
        ig_user_id=IG_ID, username="shop", token_encrypted="x", connected_by=uuid.uuid7()
    )
    session.add(account)
    await session.commit()
    return account


async def make_autoreply(session, account_id, name="Гайд") -> Autoreply:
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


async def add(session, autoreply, comment_id, *, minute=0, stage="sending", **kw) -> Delivery:
    delivery = Delivery(
        autoreply_id=autoreply.id,
        account_id=autoreply.account_id,
        comment_id=comment_id,
        media_id="m1",
        person_id=f"p-{comment_id}",
        keyword="гайд",
        created_at=T0 + timedelta(minutes=minute),
        stage=stage,
        **kw,
    )
    session.add(delivery)
    await session.commit()
    return delivery


async def comment(session, comment_id, text, username, ig_id=IG_ID) -> None:
    session.add(
        InboxEvent(
            ig_account_id=ig_id,
            kind=webhook.COMMENT,
            dedup_key=webhook.dedup_key(webhook.COMMENT, comment_id),
            payload={"id": comment_id, "text": text, "from": {"id": "1", "username": username}},
        )
    )
    await session.commit()


async def page(client, owner, account_id, **params) -> dict:
    r = await client.get(
        "/autoreplies/deliveries", headers=owner, params={"account_id": str(account_id)} | params
    )
    assert r.status_code == 200, r.text
    return r.json()


def ids(result) -> list[str]:
    return [i["comment_id"] for i in result["items"]]


async def test_newest_first_with_comment_and_autoreply(client, session, owner, account):
    autoreply = await make_autoreply(session, account.id, "Чек-лист")
    await add(session, autoreply, "c1", minute=1)
    await add(session, autoreply, "c2", minute=2, stage="delivered")
    await comment(session, "c2", "хочу чек-лист", "vasya")

    result = await page(client, owner, account.id)
    assert ids(result) == ["c2", "c1"]
    first = result["items"][0]
    assert (first["username"], first["text"], first["stage"]) == (
        "vasya",
        "хочу чек-лист",
        "delivered",
    )
    assert (first["autoreply_name"], first["keyword"]) == ("Чек-лист", "гайд")
    # коммента нет во входящих: ника и текста нет, выдача всё равно в списке
    assert (result["items"][1]["username"], result["items"][1]["text"]) == (None, None)


async def test_filter_by_stages(client, session, owner, account):
    autoreply = await make_autoreply(session, account.id)
    await add(session, autoreply, "wait", minute=1, stage="waiting_click")
    await add(session, autoreply, "dm", minute=2, stage="dm_failed")
    await add(session, autoreply, "mat", minute=3, stage="material_failed")
    await add(session, autoreply, "got", minute=4, stage="delivered")

    assert ids(await page(client, owner, account.id, stage="waiting_click")) == ["wait"]
    # «не дошло» это две ошибки сразу: этап можно повторить
    failed = await page(client, owner, account.id, stage=["dm_failed", "material_failed"])
    assert ids(failed) == ["mat", "dm"]


async def test_pages_within_stage(client, session, owner, account):
    autoreply = await make_autoreply(session, account.id)
    # между выдачами этапа лежат другие: страницы их не теряют и не повторяют
    for n in range(5):
        await add(session, autoreply, f"c{n}", minute=n, stage="delivered" if n % 2 else "clicked")
    first = await page(client, owner, account.id, stage="clicked", limit=2)
    assert ids(first) == ["c4", "c2"]
    rest = await page(client, owner, account.id, stage="clicked", limit=2, before=first["next"])
    assert ids(rest) == ["c0"]
    assert rest["next"] is None


async def test_only_own_account(client, session, owner, account):
    mine = await make_autoreply(session, account.id)
    theirs = await make_autoreply(session, uuid.uuid7())
    await add(session, mine, "mine")
    foreign = await add(session, theirs, "theirs", minute=5)
    # тот же коммент во входящих чужого аккаунта не подставляется
    await comment(session, "mine", "чужой текст", "stranger", ig_id="999")

    result = await page(client, owner, account.id)
    assert ids(result) == ["mine"]
    assert result["items"][0]["text"] is None
    # закладка из чужого аккаунта неизвестна: список не режется по чужому времени
    assert (await page(client, owner, account.id, before=str(foreign.id)))["items"] == []


async def test_counts_every_stage(client, session, owner, account):
    autoreply = await make_autoreply(session, account.id)
    await add(session, autoreply, "a", stage="waiting_click")
    await add(session, autoreply, "b", stage="waiting_click")
    await add(session, autoreply, "c", stage="delivered")
    await add(session, await make_autoreply(session, uuid.uuid7()), "x", stage="delivered")

    r = await client.get(
        "/autoreplies/deliveries/counts", headers=owner, params={"account_id": str(account.id)}
    )
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {
        "sending": 0,
        "waiting_click": 2,
        "dm_failed": 0,
        "clicked": 0,
        "follow_asked": 0,
        "material_failed": 0,
        "delivered": 1,
    }


@pytest.mark.parametrize("path", ["/autoreplies/deliveries", "/autoreplies/deliveries/counts"])
async def test_needs_login(client, account, path):
    r = await client.get(path, params={"account_id": str(account.id)})
    assert r.status_code == 401


async def test_unknown_stage(client, owner, account):
    r = await client.get(
        "/autoreplies/deliveries",
        headers=owner,
        params={"account_id": str(account.id), "stage": "maybe"},
    )
    assert r.status_code == 422


async def test_username_from_other_comment(client, session, owner, account):
    # коммента выдачи во входящих нет, но человек писал аккаунту раньше: ник оттуда
    autoreply = await make_autoreply(session, account.id)
    await add(session, autoreply, "gone")
    session.add(
        InboxEvent(
            ig_account_id=IG_ID,
            kind=webhook.COMMENT,
            dedup_key=webhook.dedup_key(webhook.COMMENT, "older"),
            payload={
                "id": "older",
                "text": "привет",
                "from": {"id": "p-gone", "username": "masha"},
            },
        )
    )
    await session.commit()
    [item] = (await page(client, owner, account.id))["items"]
    assert (item["username"], item["text"]) == ("masha", None)


async def test_same_time_not_lost_between_pages(client, session, owner, account):
    # выдачи с одним временем: на стыке страниц ни одна не теряется и не повторяется
    autoreply = await make_autoreply(session, account.id)
    ids_ = sorted(uuid.uuid7() for _ in range(3))
    for n, delivery_id in enumerate(reversed(ids_)):
        await add(session, autoreply, f"c{n}", id=delivery_id)
    seen, before = [], None
    # не больше страниц, чем выдач: сломанная закладка не уведёт тест в вечный цикл
    for _ in range(4):
        result = await page(
            client, owner, account.id, limit=1, **({"before": before} if before else {})
        )
        seen += [i["id"] for i in result["items"]]
        before = result["next"]
        if before is None:
            break
    assert seen == [str(i) for i in reversed(ids_)]
