"""Таблицы assistant. Снаружи модуля не импортируются, соседям отдаём справки."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Assistant(Base):
    """Ассистент аккаунта: отвечает на комменты, которые не взял ни один автоответ,
    по своей инструкции и базе знаний. Подключение и модель у него в ai.binding
    (purpose «assistant.answer», scope = id), здесь их нет."""

    __tablename__ = "assistant"
    __table_args__ = (
        CheckConstraint("scope IN ('all', 'posts')", name="scope_known"),
        CheckConstraint("mode IN ('direct', 'comment', 'combo')", name="mode_known"),
        CheckConstraint("daily_limit > 0", name="daily_limit_positive"),
        # общий у аккаунта один: два отвечали бы на одни и те же комменты.
        # Индекс, а не проверка в сервисе: две вкладки сохраняют разом
        Index(
            "uq_assistant_general_live",
            "account_id",
            unique=True,
            postgresql_where=text("scope = 'all' AND archived_at IS NULL"),
        ),
        {"schema": "assistant"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # наш аккаунт instagram; без внешнего ключа на чужую схему
    account_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(100))
    # all: общий, все посты без своего ассистента; posts: только из assistant_media
    scope: Mapped[str] = mapped_column(String(8))
    # пауза: не отвечает, но держит свои посты, и там молчат все
    enabled: Mapped[bool] = mapped_column(default=True)
    # в архиве: не отвечает и отпускает посты, история ответов остаётся
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # direct: в директ; comment: под комментом; combo: кратко под комментом и в директ
    mode: Mapped[str] = mapped_column(String(8))
    # тон и правила; база знаний целиком в промпт, предел длины в схеме ручки
    instruction: Mapped[str] = mapped_column(Text, server_default="")
    knowledge: Mapped[str] = mapped_column(Text, server_default="")
    # комментов в сутки (UTC): считаются все прочитанные, даже если промолчал
    daily_limit: Mapped[int] = mapped_column(SmallInteger)

    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ставит сервис при правке владельцем
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantMedia(Base):
    """Пост частного ассистента. Пост принадлежит одному живому частному (на
    паузе тоже держит), архивный его отпускает. Как autoreply_media."""

    __tablename__ = "assistant_media"
    __table_args__ = (
        # индекс не видит соседнюю таблицу, поэтому флаг архива продублирован здесь;
        # сервис ставит его в обеих таблицах одной транзакцией
        Index(
            "uq_assistant_media_live",
            "media_id",
            unique=True,
            postgresql_where=text("NOT archived"),
        ),
        {"schema": "assistant"},
    )

    assistant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(Assistant.id, ondelete="CASCADE"), primary_key=True
    )
    # id поста в Instagram, чужой: без ограничения длины
    media_id: Mapped[str] = mapped_column(Text, primary_key=True)
    archived: Mapped[bool] = mapped_column(default=False)


class Reply(Base):
    """Что ассистент сделал с одним комментом. И очередь для циклов assistant-N,
    и состояние для счётчиков «сегодня» и предела: журнал для истории, это для
    вопросов «сколько»."""

    __tablename__ = "reply"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('queued', 'thinking', 'sending', 'sent', 'send_failed', 'done')",
            name="stage_known",
        ),
        CheckConstraint(
            "outcome IN ('answered', 'unsure', 'not_mine', 'limit', 'failed', 'expired', 'paused')",
            name="outcome_known",
        ),
        # итог ставится вместе с решением: без него дальше очереди строка не идёт
        CheckConstraint(
            "stage IN ('queued', 'thinking') OR outcome IS NOT NULL", name="decided_has_outcome"
        ),
        # очередь: свежие к разбору по run_at, частичный индекс маленький
        Index("ix_reply_queue", "run_at", postgresql_where=text("stage = 'queued'")),
        # зависшие посреди запроса к нейросети: worker упал
        Index("ix_reply_stuck", "taken_at", postgresql_where=text("stage = 'thinking'")),
        # счётчики «сегодня» и предел: прочитанные ассистентом за сутки
        Index("ix_reply_assistant_taken", "assistant_id", "taken_at"),
        # вкладка «Ассистент» в журнале: ответы аккаунта страницами, свежие сверху
        Index("ix_reply_account_created", "account_id", "created_at", "id"),
        # счётчики вкладок: сколько у аккаунта на каждом итоге и стадии
        Index("ix_reply_account_outcome", "account_id", "outcome", "stage"),
        {"schema": "assistant"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # архив не удаляет ассистента, каскад только на будущее удаление целиком
    assistant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Assistant.id, ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID]
    # повтор вебхука на тот же коммент: вторая строка не встанет
    comment_id: Mapped[str] = mapped_column(Text, unique=True)
    media_id: Mapped[str] = mapped_column(Text)
    person_id: Mapped[str] = mapped_column(Text)
    comment_text: Mapped[str] = mapped_column(Text)
    # время коммента: старше 24 часов не отвечаем (expired)
    commented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    stage: Mapped[str] = mapped_column(String(12), server_default="queued")
    outcome: Mapped[str | None] = mapped_column(String(12))
    # когда брать: повтор после сбоя переносит вперёд
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # когда ассистент взял коммент: по нему предел и зависшие
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # что ушло: под комментом и в директ; пусто, если этой части нет в режиме
    comment_reply: Mapped[str | None] = mapped_column(Text)
    direct_reply: Mapped[str | None] = mapped_column(Text)
    # цитата из базы, на которую опирается ответ: видна в журнале
    source: Mapped[str | None] = mapped_column(Text)
    # код ai при failed (key_rejected, timeout…) или код Meta при send_failed
    error_code: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
