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


async def lock_unreported_outbox_task(
    session: AsyncSession, task_id: uuid.UUID
) -> OutboxTask | None:
    """Завершённая задача без отчёта под замком. None: отчитался другой."""
    return await session.scalar(
        _unreported()
        .where(OutboxTask.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def claim_unreported_outbox_task(
    session: AsyncSession, *, older_than: timedelta, max_attempts: int
) -> OutboxTask | None:
    """Самый старый не дошедший отчёт. Чужие под замком пропускаем."""
    return await session.scalar(
        _unreported()
        .where(
            OutboxTask.finished_at <= func.now() - older_than,
            OutboxTask.report_attempts < max_attempts,
            or_(OutboxTask.report_after.is_(None), OutboxTask.report_after <= func.now()),
        )
        .order_by(OutboxTask.finished_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _unreported():
    return select(OutboxTask).where(
        OutboxTask.outcome.is_not(None),
        OutboxTask.ref.is_not(None),
        OutboxTask.reported_at.is_(None),
    )


async def lock_private_replies(session: AsyncSession, account_id: uuid.UUID) -> None:
    """Private Reply одного аккаунта по очереди до конца транзакции: иначе два
    отправителя разом увидят 749 за час и оба отправят. Своя приставка ключа:
    блокировки других модулей на тот же аккаунт с этой не пересекаются."""
    key = f"instagram.private_reply:{account_id}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


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


async def last_planned_private_reply(
    session: AsyncSession, account_id: uuid.UUID
) -> datetime | None:
    """Самое позднее время среди ждущих Private Reply аккаунта: за ним следующее место."""
    return await session.scalar(
        select(func.max(OutboxTask.run_at)).where(
            OutboxTask.account_id == account_id,
            OutboxTask.kind == "private_reply",
            # на результат не влияет (у завершённых run_at в прошлом), но так запрос
            # идёт по частичному индексу ждущих, а не по всем отправленным
            OutboxTask.outcome.is_(None),
        )
    )


async def count_undelivered(
    session: AsyncSession, account_id: uuid.UUID, *, since: datetime, ref_prefix: str
) -> int:
    """Сколько отправок соседа так и не ушло: упали после повторов или опоздали к окну Meta."""
    return (
        await session.scalar(
            select(func.count()).where(
                OutboxTask.account_id == account_id,
                OutboxTask.outcome.in_(("failed", "expired")),
                OutboxTask.finished_at >= since,
                OutboxTask.ref.startswith(ref_prefix, autoescape=True),
            )
        )
        or 0
    )


async def accounts_due_refresh(session: AsyncSession, *, left: timedelta) -> list[uuid.UUID]:
    """Активные аккаунты, чей токен истекает раньше, чем через left."""
    return list(
        await session.scalars(
            select(Account.id)
            .where(Account.status == "active", Account.token_encrypted.is_not(None))
            .where(
                or_(
                    Account.token_expires_at.is_(None),
                    Account.token_expires_at < func.now() + left,
                )
            )
            .order_by(Account.token_expires_at.nulls_first())
        )
    )


async def lock_account_due_refresh(
    session: AsyncSession, account_id: uuid.UUID, *, left: timedelta
) -> Account | None:
    """Аккаунт под замком, если ему всё ещё пора: соседний worker мог обновить его
    между выборкой и замком."""
    return await session.scalar(
        select(Account)
        .where(Account.id == account_id, Account.status == "active")
        .where(Account.token_encrypted.is_not(None))
        .where(
            or_(
                Account.token_expires_at.is_(None),
                Account.token_expires_at < func.now() + left,
            )
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


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
