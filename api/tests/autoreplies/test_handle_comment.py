"""Коммент из входящих: кто отвечает под постом, выдача одна на человека и пост."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import autoreplies, instagram
from app.activity.models import Event
from app.autoreplies.models import Autoreply, AutoreplyMedia, Delivery, Keyword
from app.instagram.models import Account, OutboxTask

ACCOUNT = uuid.uuid7()
RECEIVED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def account(session) -> Account:
    # письма выдачи ссылаются на настоящий аккаунт
    account = Account(
        id=ACCOUNT,
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted="x",
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()
    return account


async def make(session, *words, scope="all", posts=(), account_id=ACCOUNT, **kw) -> Autoreply:
    autoreply = Autoreply(
        **{
            "account_id": account_id,
            "name": words[0] if words else "без слов",
            "scope": scope,
            "intro_text": "Держи",
            "button_text": "Получить",
            "reply_text": "ссылка",
            "created_by": uuid.uuid7(),
        }
        | kw
    )
    session.add(autoreply)
    await session.flush()
    session.add_all(Keyword(autoreply_id=autoreply.id, word=w, normalized=w) for w in words)
    session.add_all(
        AutoreplyMedia(autoreply_id=autoreply.id, media_id=m, archived=bool(autoreply.archived_at))
        for m in posts
    )
    await session.commit()
    return autoreply


def comment(text="хочу гайд", *, media_id="m1", person_id="p1", comment_id=None):
    return instagram.CommentRef(
        account_id=ACCOUNT,
        comment_id=comment_id or str(uuid.uuid4()),
        media_id=media_id,
        person_id=person_id,
        username="vasya",
        text=text,
        received_at=RECEIVED,
    )


async def handle(session, c) -> bool:
    taken = await autoreplies.handle_comment(session, c)
    await session.commit()
    return taken


async def deliveries(session) -> list[Delivery]:
    return list(await session.scalars(select(Delivery)))


async def journal(session) -> list[Event]:
    return list(await session.scalars(select(Event).order_by(Event.occurred_at, Event.id)))


async def winner(session, c) -> uuid.UUID | None:
    """Чей автоответ выдал на коммент; None, если никто."""
    before = {d.id for d in await deliveries(session)}
    await handle(session, c)
    new = [d for d in await deliveries(session) if d.id not in before]
    return new[0].autoreply_id if new else None


async def test_general_answers_under_any_post(session):
    general = await make(session, "гайд")
    assert await winner(session, comment(media_id="m1")) == general.id
    assert await winner(session, comment(media_id="m2", person_id="p2")) == general.id


async def test_post_taken_by_its_autoreply(session):
    await make(session, "гайд", "прайс")
    own = await make(session, "чеклист", scope="posts", posts=["m1"])
    assert await winner(session, comment("хочу чеклист")) == own.id
    # общие под этим постом молчат даже на свои слова
    assert await winner(session, comment("хочу гайд", person_id="p2")) is None
    assert await handle(session, comment("прайс", person_id="p3")) is False


async def test_disabled_own_releases_post(session):
    general = await make(session, "гайд")
    await make(session, "чеклист", scope="posts", posts=["m1"], enabled=False)
    assert await winner(session, comment("хочу гайд")) == general.id
    assert await winner(session, comment("чеклист", person_id="p2")) is None


async def test_archived_do_not_answer(session):
    archived = datetime(2026, 1, 1, tzinfo=UTC)
    await make(session, "гайд", archived_at=archived)
    await make(session, "чеклист", scope="posts", posts=["m1"], archived_at=archived)
    general = await make(session, "прайс")
    assert await winner(session, comment("гайд")) is None
    # архивный частный пост не держит: общие отвечают
    assert await winner(session, comment("прайс", person_id="p2")) == general.id
    assert await winner(session, comment("чеклист", person_id="p3")) is None


async def test_disabled_general_silent(session):
    await make(session, "гайд", enabled=False)
    assert await handle(session, comment()) is False


async def test_other_account_silent(session):
    await make(session, "гайд", account_id=uuid.uuid7())
    assert await handle(session, comment()) is False


async def test_no_word_not_ours(session):
    await make(session, "гайд")
    assert await handle(session, comment("красиво!")) is False
    assert await deliveries(session) == []
    assert await journal(session) == []


async def test_delivery_and_journal(session):
    general = await make(session, "гайд")
    c = comment()
    assert await handle(session, c) is True

    [delivery] = await deliveries(session)
    assert (
        delivery.autoreply_id,
        delivery.account_id,
        delivery.comment_id,
        delivery.media_id,
        delivery.person_id,
        delivery.keyword,
    ) == (general.id, ACCOUNT, c.comment_id, "m1", "p1", "гайд")
    [entry] = await journal(session)
    assert (entry.kind, entry.autoreply_id, entry.person_id, entry.comment_id) == (
        "autoreply.matched",
        general.id,
        "p1",
        c.comment_id,
    )
    assert entry.data == {"keyword": "гайд", "delivery_id": str(delivery.id)}
    assert entry.occurred_at == RECEIVED


async def test_repeat_under_same_post(session):
    await make(session, "гайд")
    await handle(session, comment())
    # тот же человек снова под тем же постом: коммент наш, но выдачи нет
    assert await handle(session, comment("гайд гайд")) is True
    assert len(await deliveries(session)) == 1
    assert [e.kind for e in await journal(session)][-1] == "autoreply.repeat_comment"


async def test_same_person_other_post(session):
    await make(session, "гайд")
    await handle(session, comment(media_id="m1"))
    await handle(session, comment(media_id="m2"))
    assert len(await deliveries(session)) == 2


@pytest.mark.parametrize("text", ["хочу гайд", "гайд и прайс"])
async def test_earlier_word_decides(session, text):
    guide = await make(session, "гайд")
    await make(session, "прайс")
    assert await winner(session, comment(text)) == guide.id


async def outbox(session) -> list[OutboxTask]:
    return list(await session.scalars(select(OutboxTask).order_by(OutboxTask.kind)))


async def test_delivery_queues_direct_with_button(session):
    await make(session, "гайд", intro_text="{username}, держи 👇", button_text="Получить")
    c = comment()
    await handle(session, c)
    [delivery] = await deliveries(session)

    [task] = await outbox(session)
    assert (task.kind, task.account_id, task.ref) == (
        "private_reply",
        ACCOUNT,
        f"autoreplies:{delivery.id}:intro",
    )
    assert task.payload == {
        "comment_id": c.comment_id,
        "text": "vasya, держи 👇",
        "button": {"title": "Получить", "payload": f"ar:{delivery.id}"},
    }
    # Private Reply живёт 7 дней от коммента
    assert task.expires_at == RECEIVED + timedelta(days=7)


async def test_comment_reply_with_username(session):
    await make(session, "гайд", comment_replies=["@{username}, лови в директе"])
    c = comment()
    await handle(session, c)
    [delivery] = await deliveries(session)
    comment_task = next(t for t in await outbox(session) if t.kind == "comment_reply")
    assert comment_task.payload == {"comment_id": c.comment_id, "text": "@vasya, лови в директе"}
    assert comment_task.ref == f"autoreplies:{delivery.id}:comment"


async def test_comment_replies_in_sequence(session):
    autoreply = await make(
        session, "гайд", comment_replies=["a", "b", "c"], comment_reply_mode="sequence"
    )
    for n in range(4):
        await handle(session, comment(person_id=f"p{n}"))
    texts = [
        t.payload["text"]
        for t in sorted(await outbox(session), key=lambda t: t.id)
        if t.kind == "comment_reply"
    ]
    assert texts == ["a", "b", "c", "a"]
    await session.refresh(autoreply)
    assert autoreply.last_comment_reply == 0


async def test_comment_replies_random_without_repeat(session):
    await make(session, "гайд", comment_replies=["a", "b", "c"])
    for n in range(20):
        await handle(session, comment(person_id=f"p{n}"))
    texts = [
        t.payload["text"]
        for t in sorted(await outbox(session), key=lambda t: t.id)
        if t.kind == "comment_reply"
    ]
    assert len(texts) == 20
    assert all(a != b for a, b in itertools.pairwise(texts))


async def test_no_comment_replies_only_direct(session):
    await make(session, "гайд")
    await handle(session, comment())
    assert [t.kind for t in await outbox(session)] == ["private_reply"]


async def test_repeat_queues_nothing(session):
    await make(session, "гайд", comment_replies=["a"])
    await handle(session, comment())
    await handle(session, comment("гайд ещё"))
    assert len(await outbox(session)) == 2


async def test_no_match_queues_nothing(session):
    await make(session, "гайд", comment_replies=["a"])
    await handle(session, comment("красиво"))
    assert await outbox(session) == []


async def test_rolled_back_with_comment(session):
    await make(session, "гайд", comment_replies=["a"])
    await autoreplies.handle_comment(session, comment())
    await session.rollback()
    assert await outbox(session) == []
    assert await deliveries(session) == []
