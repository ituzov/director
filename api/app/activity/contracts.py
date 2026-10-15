"""Справки activity для соседей: frozen dataclass, а не записи из базы."""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EventRef:
    """Событие журнала. Что оно значит, знает модуль, который его записал."""

    kind: str
    occurred_at: datetime
    comment_id: str | None
    autoreply_id: uuid.UUID | None
    # подробности как записал модуль; могут быть пустыми
    data: dict
