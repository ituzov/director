"""Модели assistant: инварианты держит база, а не только код."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.assistant.models import Assistant, AssistantMedia, Reply

T0 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
ACCOUNT = uuid.uuid7()


def make_assistant(**kw) -> Assistant:
    return Assistant(
        **{
            "account_id": ACCOUNT,
            "name": "Все вопросы",
            "scope": "all",
            "mode": "direct",
            "daily_limit": 200,
            "created_by": uuid.uuid7(),
        }
        | kw
    )


def make_reply(assistant: Assistant, **kw) -> Reply:
    return Reply(
        **{
            "assistant_id": assistant.id,
            "account_id": assistant.account_id,
            "comment_id": "c1",
            "media_id": "m1",
            "person_id": "p1",
            "comment_text": "А с собакой можно?",
            "commented_at": T0,
        }
        | kw
    )


async def add(session, *rows):
    session.add_all(rows)
    await session.commit()


async def test_defaults(session):
    assistant = make_assistant()
    await add(session, assistant)
    reply = make_reply(assistant)
    await add(session, reply)
    assert (assistant.enabled, assistant.instruction, assistant.knowledge) == (True, "", "")
    assert (reply.stage, reply.outcome, reply.attempts) == ("queued", None, 0)


async def test_one_live_general_per_account(session):
    # два общих отвечали бы на одни и те же комменты
    await add(session, make_assistant())
    with pytest.raises(IntegrityError):
        await add(session, make_assistant(name="Второй"))


async def test_general_after_archive_and_in_other_account(session):
    await add(session, make_assistant(archived_at=T0))
    # прошлый в архиве: новый общий можно; у соседнего аккаунта свой
    await add(session, make_assistant(), make_assistant(account_id=uuid.uuid7()))


async def test_post_has_one_live_assistant(session):
    first, second = make_assistant(scope="posts"), make_assistant(scope="posts", name="Алтай")
    await add(session, first, second)
    await add(session, AssistantMedia(assistant_id=first.id, media_id="m1"))
    with pytest.raises(IntegrityError):
        await add(session, AssistantMedia(assistant_id=second.id, media_id="m1"))


async def test_archived_assistant_releases_post(session):
    first, second = make_assistant(scope="posts"), make_assistant(scope="posts", name="Алтай")
    await add(session, first, second)
    await add(session, AssistantMedia(assistant_id=first.id, media_id="m1", archived=True))
    await add(session, AssistantMedia(assistant_id=second.id, media_id="m1"))


async def test_reply_once_per_comment(session):
    # Meta прислала коммент дважды: вторая строка не встанет
    assistant = make_assistant()
    await add(session, assistant)
    await add(session, make_reply(assistant))
    with pytest.raises(IntegrityError):
        await add(session, make_reply(assistant))


@pytest.mark.parametrize("stage", ["sending", "sent", "send_failed", "done"])
async def test_decided_reply_has_outcome(session, stage):
    assistant = make_assistant()
    await add(session, assistant)
    with pytest.raises(IntegrityError):
        await add(session, make_reply(assistant, stage=stage))


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        ("assistant", "scope", "some"),
        ("assistant", "mode", "dm"),
        ("assistant", "daily_limit", 0),
        ("reply", "stage", "waiting"),
        ("reply", "outcome", "maybe"),
    ],
)
async def test_unknown_values(session, model, field, value):
    assistant = make_assistant()
    if model == "assistant":
        setattr(assistant, field, value)
        with pytest.raises(IntegrityError):
            await add(session, assistant)
        return
    await add(session, assistant)
    reply = make_reply(assistant, outcome="answered", stage="done")
    setattr(reply, field, value)
    with pytest.raises(IntegrityError):
        await add(session, reply)
