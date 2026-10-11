"""Запросы instagram к базе. Без бизнес-правил и без commit: транзакцией
владеет сервис."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.instagram.models import Account, InboxEvent, MetaApp, OutboxTask


async def get_meta_app(session: AsyncSession) -> MetaApp | None:
    # строка всегда одна, с id = 1
    return await session.get(MetaApp, 1)


def add_meta_app(
    session: AsyncSession, *, app_id: str, app_secret_encrypted: str, verify_token: str
) -> MetaApp:
    meta_app = MetaApp(
        app_id=app_id, app_secret_encrypted=app_secret_encrypted, verify_token=verify_token
    )
    session.add(meta_app)
    return meta_app


async def claim_inbox_event(session: AsyncSession) -> InboxEvent | None:
    """Самое старое неразобранное, чей повтор уже наступил. Запирается до конца
    транзакции: второй worker его пропустит, а не будет ждать."""
    return await session.scalar(
        select(InboxEvent)
        .where(InboxEvent.processed_at.is_(None))
        .where(or_(InboxEvent.retry_at.is_(None), InboxEvent.retry_at <= func.now()))
        .order_by(InboxEvent.received_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def claim_outbox_task(session: AsyncSession) -> OutboxTask | None:
    """Самое раннее исходящее, которому пора. Запирается до конца транзакции."""
    return await session.scalar(
        select(OutboxTask)
        .where(OutboxTask.outcome.is_(None), OutboxTask.run_at <= func.now())
        .order_by(OutboxTask.run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def private_replies_last_hour(
    session: AsyncSession, account_id: uuid.UUID
) -> tuple[int, datetime | None]:
    """Сколько Private Reply аккаунт отправил за час и когда самый ранний из них."""
    count, oldest = (
        await session.execute(
            select(func.count(), func.min(OutboxTask.finished_at)).where(
                OutboxTask.account_id == account_id,
                OutboxTask.kind == "private_reply",
                OutboxTask.outcome == "sent",
                OutboxTask.finished_at > func.now() - timedelta(hours=1),
            )
        )
    ).one()
    return count, oldest


async def get_account(session: AsyncSession, account_id: uuid.UUID) -> Account | None:
    return await session.get(Account, account_id)


async def get_account_by_ig_id(session: AsyncSession, ig_user_id: str) -> Account | None:
    return await session.scalar(select(Account).where(Account.ig_user_id == ig_user_id))


async def add_inbox_events(session: AsyncSession, rows: list[dict]) -> int:
    """Положить события во входящие. Повторы (тот же dedup_key) молча пропускаются.
    Возвращает, сколько легло новых."""
    if not rows:
        return 0
    result = await session.execute(
        insert(InboxEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[InboxEvent.dedup_key])
        .returning(InboxEvent.id)
    )
    return len(result.all())


async def upsert_account(
    session: AsyncSession,
    *,
    ig_user_id: str,
    username: str,
    token_encrypted: str,
    token_expires_at: datetime,
    connected_by: uuid.UUID,
) -> Account:
    """Новый аккаунт или повторный вход того же: строка одна на ig_user_id и оживает."""
    fresh = {
        "username": username,
        "token_encrypted": token_encrypted,
        "token_expires_at": token_expires_at,
        "status": "active",
        "connected_by": connected_by,
    }
    statement = (
        insert(Account)
        .values(ig_user_id=ig_user_id, **fresh)
        .on_conflict_do_update(
            index_elements=[Account.ig_user_id],
            set_={**fresh, "connected_at": func.now(), "disconnected_at": None},
        )
        .returning(Account)
    )
    # populate_existing: если строка уже в сессии, освежить её значениями из базы
    return await session.scalar(statement, execution_options={"populate_existing": True})


async def list_accounts(session: AsyncSession) -> list[Account]:
    # сначала живые, внутри по нику: так их ищут глазами
    result = await session.scalars(
        select(Account).order_by(Account.status != "active", Account.username)
    )
    return list(result.all())
