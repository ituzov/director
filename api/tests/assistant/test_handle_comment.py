"""Коммент без автоответа: чей он. Частный ассистент поста, без него общий; на
паузе держит место; ответы на комменты и повторы вебхука не ставятся."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app import assistant, instagram
from app.assistant.models import Assistant, AssistantMedia, Reply

ACCOUNT = uuid.uuid7()
RECEIVED = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def comment(*, media_id="m1", comment_id=None, parent_id=None):
    return instagram.CommentRef(
        account_id=ACCOUNT,
        comment_id=comment_id or str(uuid.uuid4()),
        media_id=media_id,
        person_id="p1",
        username="vasya",
        text="А с собакой можно?",
        received_at=RECEIVED,
        parent_id=parent_id,
    )


async def add_assistant(session, *, posts=(), enabled=True, archived=False, name="Все вопросы"):
    a = Assistant(
        account_id=ACCOUNT,
        name=name,
        scope="posts" if posts else "all",
        mode="direct",
        daily_limit=200,
        enabled=enabled,
        archived_at=RECEIVED if archived else None,
        created_by=uuid.uuid7(),
    )
    session.add(a)
    await session.flush()
    session.add_all(AssistantMedia(assistant_id=a.id, media_id=m, archived=archived) for m in posts)
    await session.commit()
    return a


async def handle(session, c):
    taken = await assistant.handle_comment(session, c)
    await session.commit()
    return taken


async def queued(session) -> list[Reply]:
    return list(await session.scalars(select(Reply)))


async def test_general_takes_comment(session):
    general = await add_assistant(session)
    c = comment()
    assert await handle(session, c) == assistant.Taken(general.id)
    [reply] = await queued(session)
    assert (reply.assistant_id, reply.comment_id, reply.stage) == (
        general.id,
        c.comment_id,
        "queued",
    )
    # время коммента, а не постановки: по нему «старше 24 часов»
    assert (reply.comment_text, reply.commented_at) == (c.text, RECEIVED)


async def test_private_takes_its_post(session):
    await add_assistant(session)
    altai = await add_assistant(session, posts=["m1"], name="Алтай")
    assert await handle(session, comment(media_id="m1")) == assistant.Taken(altai.id)


async def test_general_on_other_posts(session):
    general = await add_assistant(session)
    await add_assistant(session, posts=["m1"], name="Алтай")
    assert await handle(session, comment(media_id="m2")) == assistant.Taken(general.id)


async def test_paused_private_lets_general_answer(session):
    # как у автоответов: на паузе частный держит пост для других частных, а ответить
    # пускает общего, иначе пауза сделала бы пост немым
    general = await add_assistant(session)
    await add_assistant(session, posts=["m1"], enabled=False, name="Алтай")
    assert await handle(session, comment(media_id="m1")) == assistant.Taken(general.id)


async def test_paused_private_without_general(session):
    await add_assistant(session, posts=["m1"], enabled=False, name="Алтай")
    assert await handle(session, comment(media_id="m1")) is None
    assert await queued(session) == []


async def test_other_account_post_not_taken(session):
    # пост с тем же id у ассистента другого аккаунта: не его коммент
    other = Assistant(
        account_id=uuid.uuid7(),
        name="Чужой",
        scope="posts",
        mode="direct",
        daily_limit=200,
        created_by=uuid.uuid7(),
    )
    session.add(other)
    await session.flush()
    session.add(AssistantMedia(assistant_id=other.id, media_id="m1"))
    await session.commit()
    general = await add_assistant(session)
    assert await handle(session, comment(media_id="m1")) == assistant.Taken(general.id)


async def test_archived_private_releases_post(session):
    general = await add_assistant(session)
    await add_assistant(session, posts=["m1"], archived=True, name="Алтай")
    assert await handle(session, comment(media_id="m1")) == assistant.Taken(general.id)


async def test_paused_or_archived_general_silent(session):
    await add_assistant(session, enabled=False)
    assert await handle(session, comment()) is None
    assert await queued(session) == []


async def test_no_assistant(session):
    assert await handle(session, comment()) is None


async def test_reply_to_comment_ignored(session):
    # ответ на коммент (чаще под нашим ответом): иначе каждый давал бы ещё директ
    await add_assistant(session)
    assert await handle(session, comment(parent_id="180000")) is None
    assert await queued(session) == []


async def test_repeat_webhook_queues_once(session):
    general = await add_assistant(session)
    c = comment(comment_id="c1")
    assert await handle(session, c) == assistant.Taken(general.id)
    # повтор того же коммента: взят тем же, но вторая строка не встаёт
    assert await handle(session, c) == assistant.Taken(general.id)
    assert await session.scalar(select(func.count()).select_from(Reply)) == 1


async def test_other_account_general_not_used(session):
    other = Assistant(
        account_id=uuid.uuid7(),
        name="Чужой",
        scope="all",
        mode="direct",
        daily_limit=200,
        created_by=uuid.uuid7(),
    )
    session.add(other)
    await session.commit()
    assert await handle(session, comment()) is None
