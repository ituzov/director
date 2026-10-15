"""Таблицы autoreplies. Снаружи модуля не импортируются, соседям отдаём справки."""

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Autoreply(Base):
    """Автоответ: на какие слова под какими постами реагировать и что говорить.
    Закончился, значит в архив: история выдач и статистика остаются в карточке."""

    __tablename__ = "autoreply"
    __table_args__ = (
        CheckConstraint("scope IN ('all', 'posts')", name="scope_known"),
        CheckConstraint(
            "comment_reply_mode IN ('random', 'sequence')", name="comment_reply_mode_known"
        ),
        # проверка подписки без текста «подпишись» оставила бы человека без ответа
        CheckConstraint("NOT follow_gate OR not_following_text IS NOT NULL", name="gate_has_text"),
        {"schema": "autoreplies"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # наш аккаунт instagram; без внешнего ключа на чужую схему
    account_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(100))
    # all: все посты аккаунта; posts: только из autoreply_media
    scope: Mapped[str] = mapped_column(String(8))
    # пауза: не отвечает, но держит свои посты и слова
    enabled: Mapped[bool] = mapped_column(default=True)
    # в архиве: не отвечает и отпускает посты и слова, история остаётся
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # первое сообщение в директ, Private Reply с кнопкой
    intro_text: Mapped[str] = mapped_column(Text)
    # лимит кнопки 20 знаков помним по Messenger, сверить с докой Instagram
    button_text: Mapped[str] = mapped_column(String(20))
    # материал: уходит после нажатия
    reply_text: Mapped[str] = mapped_column(Text)
    follow_gate: Mapped[bool] = mapped_column(default=False)
    not_following_text: Mapped[str | None] = mapped_column(Text)

    # варианты ответа под комментом; пустой список: в комментах не отвечаем
    comment_replies: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    # random: любой, кроме прошлого; sequence: по кругу
    comment_reply_mode: Mapped[str] = mapped_column(String(8), server_default="random")
    # номер прошлого варианта: с ним не повторяемся подряд в обоих режимах
    last_comment_reply: Mapped[int | None]

    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ставит сервис при правке владельцем, не onupdate: выбор ответа в комментах тоже
    # обновляет строку, но автоответ от этого не меняется
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Keyword(Base):
    """Слово или фраза автоответа, чипса в форме."""

    __tablename__ = "keyword"
    __table_args__ = (
        UniqueConstraint("autoreply_id", "normalized", name="uq_keyword_word"),
        {"schema": "autoreplies"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    autoreply_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(Autoreply.id, ondelete="CASCADE"), index=True
    )
    # как ввёл владелец: «Гайд»
    word: Mapped[str] = mapped_column(String(100))
    # токены через пробел: «гайд», «хочу гайд». По нему ищем и сравниваем
    normalized: Mapped[str] = mapped_column(String(100))


class AutoreplyMedia(Base):
    """Пост частного автоответа. Пост принадлежит одному живому частному,
    архивный его отпускает."""

    __tablename__ = "autoreply_media"
    __table_args__ = (
        # индекс не видит соседнюю таблицу, поэтому флаг архива продублирован здесь;
        # сервис ставит его в обеих таблицах одной транзакцией
        Index(
            "uq_autoreply_media_live",
            "media_id",
            unique=True,
            postgresql_where=text("NOT archived"),
        ),
        {"schema": "autoreplies"},
    )

    autoreply_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(Autoreply.id, ondelete="CASCADE"), primary_key=True
    )
    # id поста в Instagram, чужой: без ограничения длины
    media_id: Mapped[str] = mapped_column(Text, primary_key=True)
    archived: Mapped[bool] = mapped_column(default=False)


class Delivery(Base):
    """Выдача: автоответ сработал на коммент. Номер уезжает в кнопку и возвращается
    с нажатием."""

    __tablename__ = "delivery"
    __table_args__ = (
        # трижды написал «гайд» под одним постом: выдача одна
        UniqueConstraint(
            "autoreply_id", "media_id", "person_id", name="uq_delivery_person_per_post"
        ),
        {"schema": "autoreplies"},
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # каскад на будущее удаление автоответа: выдачи уходят вместе с ним
    autoreply_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Autoreply.id, ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID]
    # Meta повторила вебхук: вторая выдача на тот же коммент не ляжет
    comment_id: Mapped[str] = mapped_column(Text, unique=True)
    media_id: Mapped[str] = mapped_column(Text)
    person_id: Mapped[str] = mapped_column(Text)
    # какое слово сработало: для журнала и «почему ответили»
    keyword: Mapped[str] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ответили под комментом
    commented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ушло сообщение с кнопкой
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # первое нажатие
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # последнее нажатие: когда человек нажимал в последний раз
    last_click_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # материал выдан; после этого нажатия игнорируются
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # раунд выдачи: растёт, когда вместо материала ушла просьба подписаться или
    # материал не ушёл. Материал ставится в очередь раз за раунд, нажатия внутри
    # раунда второй не ставят
    gate_round: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # ответ под комментом, выбранный при совпадении, с ником. Уходит, только когда
    # ушёл директ: иначе «отправили в директ» под комментом было бы неправдой
    comment_reply: Mapped[str | None] = mapped_column(Text)
