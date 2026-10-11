"""Модели instagram: инварианты держит база, а не только код."""

import uuid
from datetime import UTC, datetime

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


def make_event(**kw) -> InboxEvent:
    return InboxEvent(ig_account_id="1", kind="comment", dedup_key="c1", payload={}, **kw)


async def test_inbox_unknown_outcome_rejected(session):
    session.add(make_event(processed_at=datetime.now(UTC), outcome="maybe"))
    with pytest.raises(IntegrityError, match="ck_inbox_outcome_known"):
        await session.commit()


@pytest.mark.parametrize(
    "fields",
    [
        # разобрано, но непонятно чем
        {"processed_at": datetime(2026, 1, 1, tzinfo=UTC)},
        # итог есть, а событие всё ещё в очереди
        {"outcome": "done"},
    ],
)
async def test_inbox_outcome_only_when_processed(session, fields):
    session.add(make_event(**fields))
    with pytest.raises(IntegrityError, match="ck_inbox_outcome_when_processed"):
        await session.commit()


async def test_inbox_duplicate_rejected(session):
    # Meta повторила вебхук: тот же коммент второй раз в очередь не ляжет
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


async def test_long_external_ids_fit(session):
    # длину чужих id и ника Meta не обещает: длинные ложатся, а не роняют вход и вебхук
    long_id = "1" * 100
    session.add(make_account(ig_user_id=long_id, username="u" * 100))
    session.add(InboxEvent(ig_account_id=long_id, kind="comment", dedup_key="k", payload={}))
    await session.commit()
