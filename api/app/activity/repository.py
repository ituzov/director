"""Запросы activity к базе. Без бизнес-правил и без commit: транзакцией
владеет вызывающий."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity.models import Event


def add_event(
    session: AsyncSession,
    *,
    kind: str,
    account_id: uuid.UUID | None,
    autoreply_id: uuid.UUID | None,
    person_id: str | None,
    comment_id: str | None,
    data: dict,
    occurred_at: datetime | None,
) -> None:
    session.add(
        Event(
            kind=kind,
            account_id=account_id,
            autoreply_id=autoreply_id,
            person_id=person_id,
            comment_id=comment_id,
            data=data,
            # None SQLAlchemy в INSERT не кладёт, время ставит now() базы
            occurred_at=occurred_at,
        )
    )


async def comment_events(
    session: AsyncSession, account_id: uuid.UUID, comment_ids: list[str]
) -> list[Event]:
    """События аккаунта по этим комментам, по порядку: время, при равном id."""
    query = (
        select(Event)
        .where(Event.account_id == account_id, Event.comment_id.in_(comment_ids))
        .order_by(Event.occurred_at, Event.id)
    )
    return list(await session.scalars(query))
