"""Коммент из входящих: кто отвечает под постом, выдача одна на человека и пост."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import autoreplies, instagram
from app.activity.models import Event
from app.autoreplies.models import Autoreply, AutoreplyMedia, Delivery, Keyword

ACCOUNT = uuid.uuid7()
RECEIVED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


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
