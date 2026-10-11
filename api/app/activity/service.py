"""Запись в журнал. Транзакцией владеет вызывающий: activity только добавляет строки."""

import re
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.activity import repository

# та же форма, что в CHECK базы: ловим опечатку в коде сразу, а не на commit
_KIND = re.compile(r"[a-z_]+\.[a-z_]+")


def record(
    session: AsyncSession,
    kind: str,
    *,
    account_id: uuid.UUID | None = None,
    autoreply_id: uuid.UUID | None = None,
    person_id: str | None = None,
    comment_id: str | None = None,
    data: dict | None = None,
    occurred_at: datetime | None = None,
) -> None:
    """Записать событие в сессии того, кто действует. Без commit: транзакцией
    владеет вызывающий, и при откате запись уйдёт вместе с действием.

    occurred_at: когда это случилось, если не сейчас. worker разбирает коммент
    позже, чем его написали, а в журнале нужно время коммента."""
    if not _KIND.fullmatch(kind):
        raise ValueError(f"вид события не в форме модуль.действие: {kind!r}")
    repository.add_event(
        session,
        kind=kind,
        account_id=account_id,
        autoreply_id=autoreply_id,
        person_id=person_id,
        comment_id=comment_id,
        data=data or {},
        occurred_at=occurred_at,
    )
