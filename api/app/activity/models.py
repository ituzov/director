"""Таблицы activity. Снаружи модуля не импортируются, пишут через record()."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Event(Base):
    """Событие бота для журнала и статистики. Только дописываем, не правим."""

    __tablename__ = "event"
    __table_args__ = (
        # вид события в форме модуль.действие: comment.received, reply.sent
        CheckConstraint(r"kind ~ '^[a-z_]+\.[a-z_]+$'", name="kind_format"),
        # лента и статистика аккаунта за период
        Index("ix_event_account_time", "account_id", "occurred_at"),
        # вся цепочка одного коммента
        Index("ix_event_comment", "comment_id"),
        # фильтр «по человеку»
        Index("ix_event_person", "person_id"),
        {"schema": "activity"},
    )

    # uuid7 растёт со временем: свежие события в конце индекса
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(String(64))
    # наш id аккаунта Instagram; пусто у событий установки целиком
    account_id: Mapped[uuid.UUID | None]
    autoreply_id: Mapped[uuid.UUID | None]
    # id человека и коммента в Instagram.
    # Длину чужих id Meta не обещает, поэтому без ограничения
    person_id: Mapped[str | None] = mapped_column(Text)
    comment_id: Mapped[str | None] = mapped_column(Text)
    # подробности для человека: текст коммента, причина пропуска, ошибка Meta
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
