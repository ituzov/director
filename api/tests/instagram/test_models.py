"""Модели instagram: инварианты держит база, а не только код."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.instagram.models import Account, InboxEvent, MetaApp


def make_app(**kw) -> MetaApp:
    return MetaApp(app_id="1", app_secret_encrypted="x", verify_token="t", **kw)


async def test_second_row_rejected(session):
    session.add(make_app())
    await session.commit()

    # с id = 1 не пустит первичный ключ, а с любым другим проверка single_row
    session.add(make_app(id=2))
    with pytest.raises(IntegrityError, match="ck_meta_app_single_row"):
        await session.commit()


async def test_inbox_duplicate_rejected(session):
    # Meta повторила вебхук: тот же коммент второй раз в очередь не ляжет
    def make_event() -> InboxEvent:
        return InboxEvent(ig_account_id="1", kind="comment", dedup_key="c1", payload={})

    session.add(make_event())
    await session.commit()

    session.add(make_event())
    with pytest.raises(IntegrityError, match="uq_inbox_dedup_key"):
        await session.commit()


def make_account(**kw) -> Account:
    return Account(
        **{"ig_user_id": "17841400000000000", "username": "shop", "connected_by": uuid.uuid7()}
        | {"token_encrypted": "x"}
        | kw
    )


async def test_account_twice_rejected(session):
    # тот же аккаунт Instagram вторым входом оживляет строку, а не заводит новую
    session.add(make_account())
    await session.commit()
    session.add(make_account())
    with pytest.raises(IntegrityError, match="uq_account_ig_user_id"):
        await session.commit()


async def test_active_account_needs_token(session):
    session.add(make_account(token_encrypted=None))
    with pytest.raises(IntegrityError, match="ck_account_active_has_token"):
        await session.commit()


async def test_disconnected_account_without_token(session):
    session.add(make_account(token_encrypted=None, status="disconnected"))
    await session.commit()


async def test_unknown_status_rejected(session):
    session.add(make_account(status="paused"))
    with pytest.raises(IntegrityError, match="ck_account_status_known"):
        await session.commit()
