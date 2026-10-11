"""Модели autoreplies: инварианты держит база, а не только код."""

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.autoreplies.models import Autoreply, AutoreplyMedia, Delivery, Keyword


def make_autoreply(**kw) -> Autoreply:
    return Autoreply(
        **{
            "account_id": uuid.uuid7(),
            "name": "Гайд",
            "scope": "posts",
            "intro_text": "Держи",
            "button_text": "Получить",
            "reply_text": "ссылка",
            "created_by": uuid.uuid7(),
        }
        | kw
    )


async def add(session, *rows):
    session.add_all(rows)
    await session.commit()


def make_delivery(autoreply: Autoreply, **kw) -> Delivery:
    return Delivery(
        **{
            "autoreply_id": autoreply.id,
            "account_id": autoreply.account_id,
            "comment_id": "c1",
            "media_id": "m1",
            "person_id": "p1",
            "keyword": "гайд",
        }
        | kw
    )


async def test_unknown_scope_rejected(session):
    session.add(make_autoreply(scope="some"))
    with pytest.raises(IntegrityError, match="ck_autoreply_scope_known"):
        await session.commit()


async def test_unknown_comment_reply_mode_rejected(session):
    session.add(make_autoreply(comment_reply_mode="shuffle"))
    with pytest.raises(IntegrityError, match="ck_autoreply_comment_reply_mode_known"):
        await session.commit()


async def test_gate_needs_text(session):
    session.add(make_autoreply(follow_gate=True))
    with pytest.raises(IntegrityError, match="ck_autoreply_gate_has_text"):
        await session.commit()


async def test_same_word_twice_rejected(session):
    autoreply = make_autoreply()
    await add(session, autoreply)
    session.add_all(
        [
            Keyword(autoreply_id=autoreply.id, word="Гайд", normalized="гайд"),
            Keyword(autoreply_id=autoreply.id, word="гайд", normalized="гайд"),
        ]
    )
    with pytest.raises(IntegrityError, match="uq_keyword_word"):
        await session.commit()


async def test_post_belongs_to_one_live_autoreply(session):
    first, second = make_autoreply(), make_autoreply()
    await add(session, first, second)
    await add(session, AutoreplyMedia(autoreply_id=first.id, media_id="m1"))
    session.add(AutoreplyMedia(autoreply_id=second.id, media_id="m1"))
    with pytest.raises(IntegrityError, match="uq_autoreply_media_live"):
        await session.commit()


async def test_archived_releases_post(session):
    old, new = make_autoreply(), make_autoreply()
    await add(session, old, new)
    await add(session, AutoreplyMedia(autoreply_id=old.id, media_id="m1", archived=True))
    # архивный пост не держит: новый частный на тот же пост ложится
    await add(session, AutoreplyMedia(autoreply_id=new.id, media_id="m1"))


async def test_one_delivery_per_comment(session):
    autoreply = make_autoreply()
    await add(session, autoreply)
    await add(session, make_delivery(autoreply))
    # Meta повторила вебхук, а человек другой у того же коммента не бывает:
    # отличаем только по comment_id
    session.add(make_delivery(autoreply, person_id="p2"))
    with pytest.raises(IntegrityError, match="uq_delivery_comment_id"):
        await session.commit()


async def test_one_delivery_per_person_and_post(session):
    autoreply = make_autoreply()
    await add(session, autoreply)
    await add(session, make_delivery(autoreply))
    # тот же человек второй раз написал «гайд» под тем же постом
    session.add(make_delivery(autoreply, comment_id="c2"))
    with pytest.raises(IntegrityError, match="uq_delivery_person_per_post"):
        await session.commit()


async def test_deleting_autoreply_takes_its_rows(session):
    autoreply = make_autoreply()
    await add(session, autoreply)
    await add(
        session,
        Keyword(autoreply_id=autoreply.id, word="гайд", normalized="гайд"),
        AutoreplyMedia(autoreply_id=autoreply.id, media_id="m1"),
        make_delivery(autoreply),
    )
    await session.execute(delete(Autoreply).where(Autoreply.id == autoreply.id))
    await session.commit()
    for model in (Keyword, AutoreplyMedia, Delivery):
        assert (await session.scalars(select(model))).all() == []


async def test_delivery_starts_at_round_zero(session):
    autoreply = make_autoreply()
    await add(session, autoreply)
    delivery = make_delivery(autoreply)
    await add(session, delivery)
    await session.refresh(delivery)
    assert delivery.gate_round == 0
