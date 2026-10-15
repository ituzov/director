"""Лента входящих: что пришло от Meta на аккаунт и кто это взял. Свежие сверху,
страницы по закладке, только свой аккаунт, сырой вебхук наружу не уходит."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.instagram import service, webhook
from app.instagram.models import Account, InboxEvent

IG_ID = "17841400000000000"
T0 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


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


async def add(session, kind, payload, *, minute=0, ig_id=IG_ID, **kw) -> InboxEvent:
    event = InboxEvent(
        ig_account_id=ig_id,
        kind=kind,
        dedup_key=f"{kind}:{uuid.uuid4()}",
        payload=payload,
        received_at=T0 + timedelta(minutes=minute),
        **kw,
    )
    session.add(event)
    await session.commit()
    return event


def comment(text="хочу гайд", person="500001", username="vasya") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "text": text,
        "from": {"id": person, "username": username},
        "media": {"id": "190001"},
    }


def done(**kw) -> dict:
    return {"outcome": "done", "processed_at": T0} | kw


async def feed(client, account, owner, **params) -> dict:
    r = await client.get(f"/instagram/accounts/{account.id}/inbox", headers=owner, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_newest_first_by_pages(client, session, account, owner):
    old = await add(session, webhook.COMMENT, comment("раз"), minute=1)
    mid = await add(session, webhook.COMMENT, comment("два"), minute=2)
    new = await add(session, webhook.COMMENT, comment("три"), minute=3)

    page = await feed(client, account, owner, limit=2)
    assert [i["id"] for i in page["items"]] == [str(new.id), str(mid.id)]
    assert page["next"] == str(mid.id)

    rest = await feed(client, account, owner, limit=2, before=page["next"])
    assert [i["id"] for i in rest["items"]] == [str(old.id)]
    assert rest["next"] is None


async def test_same_time_not_lost_between_pages(client, session, account, owner):
    # время прихода совпало: на стыке страниц ни одно не теряется и не повторяется
    events = [await add(session, webhook.COMMENT, comment(str(n)), minute=5) for n in range(3)]
    first = await feed(client, account, owner, limit=2)
    second = await feed(client, account, owner, limit=2, before=first["next"])
    seen = [i["id"] for i in first["items"] + second["items"]]
    assert sorted(seen) == sorted(str(e.id) for e in events)


async def test_kinds_shown_and_parsed(client, session, account, owner):
    comment_payload = comment("хочу гайд")
    await add(
        session,
        webhook.COMMENT,
        comment_payload,
        minute=1,
        **done(handled_by="autoreplies", handled_ref="a1"),
    )
    await add(
        session,
        webhook.POSTBACK,
        {"sender": {"id": "500001"}, "postback": {"mid": "m1", "title": "Получить"}},
        minute=2,
        **done(handled_by="autoreplies", handled_ref="a1"),
    )
    await add(
        session,
        webhook.MESSAGE,
        {"sender": {"id": "700001"}, "message": {"text": "привет"}},
        minute=3,
    )
    await add(
        session,
        webhook.MESSAGE,
        {"sender": {"id": "700001"}, "message": {"attachments": [{"type": "ig_reel"}]}},
        minute=4,
    )
    # прочтения ничего не говорят о человеке: в ленту не попадают
    await add(session, webhook.READ, {"sender": {"id": "500001"}, "read": {"mid": "m1"}}, minute=5)

    items = (await feed(client, account, owner))["items"]
    got = [
        (i["kind"], i["username"], i["person_id"], i["text"], i["attachment"], i["media_id"])
        for i in items
    ]
    assert got == [
        ("message", None, "700001", None, "ig_reel", None),
        ("message", None, "700001", "привет", None, None),
        # ник нажатия по комменту того же человека: Meta его в нажатии не присылает
        ("postback", "vasya", "500001", "Получить", None, None),
        ("comment", "vasya", "500001", "хочу гайд", None, "190001"),
    ]
    assert (items[2]["handled_by"], items[2]["handled_ref"]) == ("autoreplies", "a1")
    # id коммента у Meta только у коммента: по нему web спросит, что было дальше
    assert [i["comment_id"] is not None for i in items] == [False, False, False, True]
    assert items[3]["comment_id"] == comment_payload["id"]
    # сырой вебхук наружу не уходит
    assert "payload" not in items[0]


async def test_outcomes_shown(client, session, account, owner):
    await add(session, webhook.COMMENT, comment(), minute=1, **done())
    await add(
        session,
        webhook.COMMENT,
        comment(),
        minute=2,
        **done(outcome="skipped", reason="own_comment"),
    )
    # worker ещё не дошёл: итога нет
    await add(session, webhook.COMMENT, comment(), minute=3)

    items = (await feed(client, account, owner))["items"]
    assert [(i["outcome"], i["reason"], i["handled_by"]) for i in items] == [
        (None, None, None),
        ("skipped", "own_comment", None),
        # разобрано, но ни один автоответ не подошёл
        ("done", None, None),
    ]


async def test_only_own_account(client, session, account, owner):
    await add(session, webhook.COMMENT, comment("чужой"), ig_id="999")
    mine = await add(session, webhook.COMMENT, comment("мой"))
    assert [i["id"] for i in (await feed(client, account, owner))["items"]] == [str(mine.id)]


async def test_username_only_from_own_account(client, session, account, owner):
    # ник того же id в чужом аккаунте не подставляем: лента только про свой
    await add(session, webhook.COMMENT, comment(username="stranger"), ig_id="999")
    await add(session, webhook.POSTBACK, {"sender": {"id": "500001"}, "postback": {"title": "Ок"}})
    [item] = (await feed(client, account, owner))["items"]
    assert (item["person_id"], item["username"]) == ("500001", None)


async def test_broken_payload_does_not_break_feed(client, session, account, owner):
    # вебхук пишет Meta: поля бывают не того типа
    await add(session, webhook.COMMENT, {"from": "x", "text": 5, "media": []})
    await add(session, webhook.MESSAGE, {"sender": [], "message": {"attachments": "x"}})
    items = (await feed(client, account, owner))["items"]
    assert [(i["kind"], i["person_id"], i["username"]) for i in items] == [
        ("message", None, None),
        ("comment", None, None),
    ]


async def test_unknown_bookmark_gives_empty_page(client, account, owner):
    page = await feed(client, account, owner, before=str(uuid.uuid7()))
    assert page == {"items": [], "next": None}


async def test_unknown_account(client, owner):
    r = await client.get(f"/instagram/accounts/{uuid.uuid7()}/inbox", headers=owner)
    assert (r.status_code, r.json()) == (404, {"detail": "AccountNotFound"})


async def test_needs_login(client, account):
    r = await client.get(f"/instagram/accounts/{account.id}/inbox")
    assert r.status_code == 401


async def test_same_time_order_does_not_depend_on_insert_order(client, session, account, owner):
    # id растут, а вставляем по возрастанию: порядок держит сортировка, а не случай
    ids = sorted(uuid.uuid7() for _ in range(3))
    for event_id in ids:
        await add(session, webhook.COMMENT, comment(), minute=5, id=event_id)
    seen, before = [], None
    # не больше страниц, чем событий: сломанная закладка не уведёт тест в вечный цикл
    for _ in range(len(ids) + 1):
        page = await feed(client, account, owner, limit=1, **({"before": before} if before else {}))
        seen += [i["id"] for i in page["items"]]
        before = page["next"]
        if before is None:
            break
    assert seen == [str(i) for i in reversed(ids)]


async def test_exact_limit_has_no_next(client, session, account, owner):
    await add(session, webhook.COMMENT, comment(), minute=1)
    await add(session, webhook.COMMENT, comment(), minute=2)
    assert (await feed(client, account, owner, limit=2))["next"] is None


async def test_unknown_bookmark_with_events(client, session, account, owner):
    await add(session, webhook.COMMENT, comment())
    assert (await feed(client, account, owner, before=str(uuid.uuid7())))["items"] == []


async def test_bookmark_of_other_account_is_unknown(client, session, account, owner):
    # переключили аккаунт со старой страницей: ленту не режем по чужому времени
    await add(session, webhook.COMMENT, comment(), minute=1)
    foreign = await add(session, webhook.COMMENT, comment(), minute=5, ig_id="999")
    assert (await feed(client, account, owner, before=str(foreign.id)))["items"] == []


async def test_disconnected_account_keeps_history(client, session, account, owner):
    event = await add(session, webhook.COMMENT, comment())
    account.status, account.token_encrypted = "disconnected", None
    await session.commit()
    assert [i["id"] for i in (await feed(client, account, owner))["items"]] == [str(event.id)]


async def test_username_latest_with_name(client, session, account, owner):
    await add(session, webhook.COMMENT, comment(username="old"), minute=1)
    await add(session, webhook.COMMENT, comment(username="new"), minute=2)
    # свежий коммент без ника не затирает известный
    await add(
        session, webhook.COMMENT, {"id": "c3", "text": "x", "from": {"id": "500001"}}, minute=3
    )
    await add(
        session,
        webhook.POSTBACK,
        {"sender": {"id": "500001"}, "postback": {"title": "Ок"}},
        minute=4,
    )
    items = (await feed(client, account, owner))["items"]
    assert [(i["kind"], i["username"]) for i in items] == [
        ("postback", "new"),
        # у коммента без ника ник подставляется из прошлых
        ("comment", "new"),
        # у коммента с ником остаётся его собственный, а не свежий
        ("comment", "new"),
        ("comment", "old"),
    ]


async def test_wrong_types_become_empty(client, session, account, owner):
    # вебхук пишет Meta: ни объект, ни список, ни bool не становятся текстом
    await add(
        session,
        webhook.COMMENT,
        {
            "id": {"x": 1},
            "text": {"a": 1},
            "from": {"id": "500001", "username": {"x": 1}},
            "media": {"id": True},
        },
        minute=1,
    )
    await add(
        session, webhook.POSTBACK, {"sender": {"id": "500001"}, "postback": {"title": []}}, minute=2
    )
    await add(
        session,
        webhook.MESSAGE,
        {"sender": {"id": "500001"}, "message": {"attachments": [{"type": {}}]}},
        minute=3,
    )
    items = (await feed(client, account, owner))["items"]
    fields = ("text", "attachment", "media_id", "username", "comment_id")
    got = [tuple(i[f] for f in fields) for i in items]
    assert got == [(None,) * 5] * 3


async def test_message_with_text_has_no_attachment_label(client, session, account, owner):
    payload = {
        "sender": {"id": "1"},
        "message": {"text": "смотри", "attachments": [{"type": "ig_reel"}]},
    }
    await add(session, webhook.MESSAGE, payload)
    [item] = (await feed(client, account, owner))["items"]
    assert (item["text"], item["attachment"]) == ("смотри", None)


async def mixed(session) -> dict[str, InboxEvent]:
    """Лента вперемешку: выдачи (взятые комменты) через одну с другими событиями."""
    taken = done(handled_by="autoreplies", handled_ref="a1")
    return {
        "taken1": await add(session, webhook.COMMENT, comment("гайд"), minute=1, **taken),
        "nobody": await add(session, webhook.COMMENT, comment("класс"), minute=2, **done()),
        "taken2": await add(session, webhook.COMMENT, comment("гайд"), minute=3, **taken),
        "press": await add(
            session,
            webhook.POSTBACK,
            {"sender": {"id": "500001"}, "postback": {"title": "Ок"}},
            minute=4,
            **taken,
        ),
        "taken3": await add(session, webhook.COMMENT, comment("гайд"), minute=5, **taken),
        "message": await add(
            session, webhook.MESSAGE, {"sender": {"id": "1"}, "message": {"text": "x"}}, minute=6
        ),
        "queued": await add(session, webhook.COMMENT, comment("гайд"), minute=7),
    }


def ids(page, events, *names) -> bool:
    return [i["id"] for i in page["items"]] == [str(events[n].id) for n in names]


async def test_filter_by_kind(client, session, account, owner):
    events = await mixed(session)
    assert ids(await feed(client, account, owner, kind="postback"), events, "press")
    assert ids(
        await feed(client, account, owner, kind="comment"),
        events,
        "queued",
        "taken3",
        "taken2",
        "nobody",
        "taken1",
    )


async def test_filter_by_taken(client, session, account, owner):
    events = await mixed(session)
    assert ids(
        await feed(client, account, owner, taken="true"),
        events,
        "taken3",
        "press",
        "taken2",
        "taken1",
    )
    # ничьи: никто не взял и ещё не разобранные
    assert ids(
        await feed(client, account, owner, taken="false"), events, "queued", "message", "nobody"
    )


async def test_deliveries_by_pages(client, session, account, owner):
    # выдачи это взятые комменты; между ними другие события, страницы их не теряют
    events = await mixed(session)
    params = {"kind": "comment", "taken": "true", "limit": 2}
    first = await feed(client, account, owner, **params)
    assert ids(first, events, "taken3", "taken2")
    rest = await feed(client, account, owner, before=first["next"], **params)
    assert ids(rest, events, "taken1")
    assert rest["next"] is None


async def test_unknown_kind(client, account, owner):
    r = await client.get(
        f"/instagram/accounts/{account.id}/inbox", headers=owner, params={"kind": "read"}
    )
    assert r.status_code == 422


async def test_reads_never_shown_even_past_route(session, account):
    # ручка чужой вид не пустит, но сервис не должен на это полагаться
    await add(session, webhook.READ, {"sender": {"id": "1"}, "read": {"mid": "m1"}})
    page = await service.list_inbox(session, account.id, before=None, limit=50, kind="read")
    assert [i.kind for i in page.items] == []
