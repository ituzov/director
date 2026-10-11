"""Таблицы instagram. Снаружи модуля не импортируются, соседям отдаём справки."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MetaApp(Base):
    """Приложение Meta установки: одно на всех, через него подключаются все аккаунты."""

    __tablename__ = "meta_app"
    __table_args__ = (
        # строка ровно одна, это держит база, а не только код
        CheckConstraint("id = 1", name="single_row"),
        {"schema": "instagram"},
    )
    # updated_at считает база: забираем его RETURNING-ом сразу после UPDATE,
    # иначе чтение в ответе станет скрытым запросом, а в async это ошибка
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    # Instagram App ID, не секрет: он виден в адресе OAuth
    app_id: Mapped[str] = mapped_column(String(32))
    # Instagram App Secret, зашифрован core.crypto. Им же подписаны вебхуки
    app_secret_encrypted: Mapped[str]
    # пароль проверки адреса вебхука: генерирует Директор, владелец копирует в Meta
    verify_token: Mapped[str] = mapped_column(String(64))
    # когда меняли ключи. Ставит save_meta_app, а не onupdate: подтверждение вебхука
    # тоже обновляет строку, но ключи от этого не меняются
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # когда Meta последний раз подтвердила адрес вебхука нашим маркером.
    # Самопроверка админки сюда не пишет: это знак, что владелец прошёл шаг в кабинете
    webhook_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboxEvent(Base):
    """Вебхук Meta, принятый, но ещё не разобранный. Вебхук только кладёт сюда
    и сразу отвечает 200, разбирает worker. Разобранные стираем через неделю:
    в payload текст коммента и id человека."""

    __tablename__ = "inbox"
    __table_args__ = (
        # очередь worker: неразобранные по порядку прихода, разобранные индекс не раздувают
        Index(
            "ix_inbox_pending",
            "received_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
        {"schema": "instagram"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # id аккаунта Instagram из entry[].id: чей это вебхук
    ig_account_id: Mapped[str] = mapped_column(String(32))
    # comment, message, postback
    kind: Mapped[str] = mapped_column(String(16))
    # Meta повторяет вебхуки: id коммента или mid сообщения, второй раз не ляжет
    dedup_key: Mapped[str] = mapped_column(String(128), unique=True)
    # одно событие как прислала Meta: changes[].value или messaging[]
    payload: Mapped[dict] = mapped_column(JSONB)
    # id запроса вебхука: worker поднимает его в логи, цепочка читается по одному id
    request_id: Mapped[str | None] = mapped_column(String(64))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
