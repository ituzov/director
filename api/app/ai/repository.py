"""Запросы ai к базе. Без бизнес-правил и без commit: транзакцией владеет сервис."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import Connection


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
    """lock: запереть строку до конца транзакции, чтобы соседняя замена ключа ждала."""
    query = select(Connection).where(Connection.id == connection_id)
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


async def list_connections(session: AsyncSession) -> list[Connection]:
    return list(await session.scalars(select(Connection).order_by(Connection.created_at)))
