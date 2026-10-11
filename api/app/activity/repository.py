"""Запросы activity к базе. Без бизнес-правил и без commit: транзакцией
владеет вызывающий."""

import uuid
from datetime import datetime

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
