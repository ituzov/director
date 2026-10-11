"""Справки instagram для соседей: frozen dataclass, а не записи из базы."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class CommentRef:
    """Коммент под постом, разобранный из входящих."""

    # наш аккаунт, под чьим постом написали
    account_id: uuid.UUID
    # на него отвечают Private Reply
    comment_id: str
    # пост
    media_id: str
    # автор; тот же id, что у него в директе
    person_id: str
    username: str | None
    text: str
    # когда Meta прислала вебхук: время коммента для журнала
    received_at: datetime


@dataclass(frozen=True, slots=True)
class InboxHandlers:
    """Кому отдать разобранное из входящих. Собирает worker, порядок
    «сначала автоответы, потом ассистент» тоже его. None: этот вид пока
    никому не нужен, событие просто отмечается разобранным."""

    on_comment: Callable[[AsyncSession, CommentRef], Awaitable[None]] | None = None
