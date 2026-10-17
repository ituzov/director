"""Вкладка «Ассистент» в журнале: ответы страницами, вкладки и их счётчики по одним
правилам, шаги ассистента по комменту. Чужой аккаунт не виден."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import activity
from app.assistant.models import Assistant, Reply

T0 = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


async def add_assistant(session, account_id, name="Все вопросы") -> Assistant:
    a = Assistant(
        account_id=account_id,
        name=name,
        scope="all",
        mode="combo",
        daily_limit=200,
        created_by=uuid.uuid7(),
    )
    session.add(a)
    await session.commit()
    return a


async def add_reply(session, a, n, outcome, stage, **kw) -> Reply:
    reply = Reply(
        assistant_id=a.id,
        account_id=a.account_id,
        comment_id=f"c{n}-{uuid.uuid4().hex[:6]}",
        media_id="m1",
        person_id="p1",
        comment_text=f"коммент {n}",
        commented_at=T0,
        outcome=outcome,
        stage=stage,
        created_at=T0 + timedelta(minutes=n),
        **kw,
    )
    session.add(reply)
    await session.commit()
    return reply


# итог, стадия и вкладка, в которую строка должна попасть
ROWS = [
    ("answered", "sent", "answered"),
    ("answered", "sending", "answered"),
    # ответ написали, но он не дошёл: это «не ответил», а не «ответил»
    ("answered", "send_failed", "missed"),
    ("unsure", "done", "unsure"),
    ("not_mine", "done", "not_mine"),
    ("failed", "done", "missed"),
    ("limit", "done", "missed"),
    ("expired", "done", "missed"),
    ("paused", "done", "missed"),
    # ещё в очереди: только во «Всех»
    (None, "queued", None),
]


@pytest.fixture
async def journal(session):
    account_id = uuid.uuid7()
    a = await add_assistant(session, account_id)
    rows = [await add_reply(session, a, n, o, s) for n, (o, s, _) in enumerate(ROWS)]
    # чужой аккаунт: не должен попасть ни в список, ни в счётчики
    other = await add_assistant(session, uuid.uuid7(), name="Чужой")
    await add_reply(session, other, 99, "answered", "sent")
    return account_id, a, rows


async def page(client, owner, account_id, **params):
    r = await client.get(
        "/assistants/replies", headers=owner, params={"account_id": str(account_id), **params}
    )
    assert r.status_code == 200
    return r.json()


@pytest.mark.parametrize("tab", ["answered", "unsure", "not_mine", "missed"])
async def test_tab_filters_and_counts_agree(client, owner, journal, tab):
    account_id, _, rows = journal
    body = await page(client, owner, account_id, tab=tab)
    want = [str(r.id) for r, (_, _, t) in zip(rows, ROWS, strict=True) if t == tab]
    # свежие сверху
    assert [i["id"] for i in body["items"]] == list(reversed(want))
    counts = (
        await client.get(
            "/assistants/replies/counts", headers=owner, params={"account_id": str(account_id)}
        )
    ).json()["counts"]
    # счётчик вкладки и её список считаются по одним правилам
    assert counts[tab] == len(want)
    assert counts["all"] == len(ROWS)


async def test_all_and_paging(client, owner, journal):
    account_id, a, rows = journal
    first = await page(client, owner, account_id, limit=4)
    assert [i["id"] for i in first["items"]] == [str(r.id) for r in reversed(rows[-4:])]
    assert first["items"][0]["assistant_name"] == "Все вопросы"
    rest = await page(client, owner, account_id, before=first["next"], limit=50)
    assert [i["id"] for i in rest["items"]] == [str(r.id) for r in reversed(rows[:-4])]
    assert rest["next"] is None


async def test_other_account_anchor_is_unknown(client, owner, journal, session):
    account_id, _, _ = journal
    stranger = await add_assistant(session, uuid.uuid7(), name="Ещё чужой")
    anchor = await add_reply(session, stranger, 50, "answered", "sent")
    # закладка чужого аккаунта резала бы список по чужому времени
    assert (await page(client, owner, account_id, before=str(anchor.id)))["items"] == []


async def test_history_steps(client, owner, journal, session):
    account_id, a, rows = journal
    reply = rows[0]
    for kind, data in [
        ("assistant.answered", {"assistant_id": str(a.id), "reply_id": str(reply.id)}),
        ("assistant.sent", {"reply_id": str(reply.id), "part": "direct", "reason": None}),
        ("assistant.send_failed", {"reply_id": str(reply.id), "part": "comment", "reason": "100"}),
        # шаг автоответа по тому же комменту ассистенту не нужен
        ("autoreply.clicked", {}),
    ]:
        activity.record(
            session,
            kind,
            account_id=account_id,
            person_id="p1",
            comment_id=reply.comment_id,
            data=data,
        )
        await session.commit()
    r = await client.get(
        "/assistants/history",
        headers=owner,
        params={"account_id": str(account_id), "comment_id": [reply.comment_id]},
    )
    steps = r.json()["comments"][reply.comment_id]
    assert [(s["step"], s["part"], s["reason"]) for s in steps] == [
        ("answered", None, None),
        ("sent", "direct", None),
        ("send_failed", "comment", "100"),
    ]
    assert steps[0]["assistant_id"] == str(a.id)


async def test_member_reads(client, login_as, journal):
    # журнал смотрят все вошедшие, как у автоответов
    account_id, _, _ = journal
    member = await login_as("member")
    assert len((await page(client, member, account_id))["items"]) == len(ROWS)


async def test_anonymous(client, journal):
    account_id, _, _ = journal
    for path in ("/assistants/replies", "/assistants/replies/counts"):
        r = await client.get(path, params={"account_id": str(account_id)})
        assert r.status_code == 401


OUTCOMES = [None, "answered", "unsure", "not_mine", "limit", "failed", "expired", "paused"]
STAGES = ["queued", "thinking", "sending", "sent", "send_failed", "done"]


async def test_every_allowed_row_in_one_tab(client, owner, session):
    # все пары итог и стадия, которые пропускают проверки базы: каждая решённая строка
    # ровно в одной вкладке, нерешённая только во «Всех», счётчики совпадают со списками
    account_id = uuid.uuid7()
    a = await add_assistant(session, account_id)
    rows = {}
    n = 0
    for outcome in OUTCOMES:
        for stage in STAGES:
            if outcome is None and stage not in ("queued", "thinking"):
                continue
            n += 1
            rows[(await add_reply(session, a, n, outcome, stage)).id] = (outcome, stage)
    seen: dict[str, list[str]] = {str(i): [] for i in rows}
    counts = (
        await client.get(
            "/assistants/replies/counts", headers=owner, params={"account_id": str(account_id)}
        )
    ).json()["counts"]
    for tab in ("answered", "unsure", "not_mine", "missed"):
        items = (await page(client, owner, account_id, tab=tab, limit=100))["items"]
        assert counts[tab] == len(items), tab
        for item in items:
            seen[item["id"]].append(tab)
    for reply_id, (outcome, stage) in rows.items():
        tabs = seen[str(reply_id)]
        assert len(tabs) == (0 if outcome is None else 1), (outcome, stage, tabs)
    assert counts["all"] == len(rows)


async def test_paging_with_same_time(client, owner, session):
    # строки с одним временем: закладка делит их по id, ничего не теряется и не повторяется
    account_id = uuid.uuid7()
    a = await add_assistant(session, account_id)
    ids = []
    for _ in range(5):
        r = await add_reply(session, a, 0, "answered", "sent")
        ids.append(str(r.id))
    first = await page(client, owner, account_id, limit=2)
    second = await page(client, owner, account_id, before=first["next"], limit=2)
    third = await page(client, owner, account_id, before=second["next"], limit=2)
    got = [i["id"] for p in (first, second, third) for i in p["items"]]
    assert sorted(got) == sorted(ids) and len(set(got)) == 5


async def test_history_other_account_hidden(client, owner, journal, session):
    account_id, a, rows = journal
    reply = rows[0]
    activity.record(
        session,
        "assistant.answered",
        account_id=account_id,
        person_id="p1",
        comment_id=reply.comment_id,
        data={"assistant_id": str(a.id)},
    )
    await session.commit()
    r = await client.get(
        "/assistants/history",
        headers=owner,
        params={"account_id": str(uuid.uuid7()), "comment_id": [reply.comment_id]},
    )
    assert r.json()["comments"] == {}


async def test_history_anonymous(client, journal):
    account_id, _, rows = journal
    r = await client.get(
        "/assistants/history",
        params={"account_id": str(account_id), "comment_id": [rows[0].comment_id]},
    )
    assert r.status_code == 401
