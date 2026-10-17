"""Запросы ai к базе. Без бизнес-правил и без commit: транзакцией владеет сервис."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import Binding, Call, Connection


def add_connection(
    session: AsyncSession,
    *,
    provider: str,
    name: str,
    key_encrypted: str,
    key_hint: str,
    base_url: str | None,
    key_changed_at: datetime,
    checked_at: datetime | None,
    error_code: str | None,
    error_at: datetime | None,
    created_by: uuid.UUID,
) -> Connection:
    connection = Connection(
        provider=provider,
        name=name,
        key_encrypted=key_encrypted,
        key_hint=key_hint,
        base_url=base_url,
        key_changed_at=key_changed_at,
        checked_at=checked_at,
        error_code=error_code,
        error_at=error_at,
        created_by=created_by,
    )
    session.add(connection)
    return connection


async def get_connection(
    session: AsyncSession, connection_id: uuid.UUID, *, lock: bool = False
) -> Connection | None:
    """lock: запереть строку до конца транзакции, чтобы соседняя замена ключа ждала.
    Под замком значения перечитываются: объект, прочитанный раньше в этой же
    сессии, иначе остался бы со старыми."""
    query = select(Connection).where(Connection.id == connection_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(query)


async def list_connections(session: AsyncSession) -> list[Connection]:
    return list(await session.scalars(select(Connection).order_by(Connection.created_at)))


async def get_binding(
    session: AsyncSession, *, purpose: str, scope: str | None, lock: bool = False
) -> Binding | None:
    query = select(Binding).where(
        Binding.purpose == purpose,
        Binding.scope.is_(None) if scope is None else Binding.scope == scope,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(query)


async def list_bindings(session: AsyncSession, connection_ids: list[uuid.UUID]) -> list[Binding]:
    """Настройки задач на этих подключениях, одним запросом на весь список."""
    if not connection_ids:
        return []
    return list(
        await session.scalars(
            select(Binding)
            .where(Binding.connection_id.in_(connection_ids))
            .order_by(Binding.purpose, Binding.model)
        )
    )


async def upsert_binding(
    session: AsyncSession,
    *,
    purpose: str,
    scope: str | None,
    connection_id: uuid.UUID,
    model: str,
) -> None:
    """Одна строка на задачу и область: вторая настройка заменяет первую.
    Сменили модель: пометка «модели нет» про старую, её снимаем."""
    values = {"connection_id": connection_id, "model": model, "model_missing_at": None}
    await session.execute(
        insert(Binding)
        .values(purpose=purpose, scope=scope, **values)
        .on_conflict_do_update(index_elements=["purpose", "scope"], set_=values)
    )


def add_call(session: AsyncSession, **fields) -> Call:
    call = Call(**fields)
    session.add(call)
    return call


async def clear_model_missing(session: AsyncSession, connection_id: uuid.UUID) -> None:
    """Пометка «модели нет» была про старый ключ: новому модель может быть доступна."""
    await session.execute(
        update(Binding).where(Binding.connection_id == connection_id).values(model_missing_at=None)
    )
