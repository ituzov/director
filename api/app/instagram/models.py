"""Таблицы instagram. Снаружи модуля не импортируются, соседям отдаём справки."""

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
    """Вебхук Meta. Вебхук только кладёт сюда и сразу отвечает 200, разбирает
    worker по одному событию в транзакции. Разобранные стираем через неделю:
    в payload текст коммента и id человека."""

    __tablename__ = "inbox"
    __table_args__ = (
        # очередь worker: неразобранные по порядку прихода, разобранные индекс не раздувают
        Index(
            "ix_inbox_pending",
            "received_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
        CheckConstraint("outcome IN ('done', 'skipped', 'failed')", name="outcome_known"),
        # итог есть ровно у разобранного: «разобрано, но непонятно чем» не бывает
        CheckConstraint(
            "(processed_at IS NULL) = (outcome IS NULL)", name="outcome_when_processed"
        ),
        {"schema": "instagram"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # id аккаунта Instagram из entry[].id: чей это вебхук. Длину чужих id Meta не
    # обещает, поэтому без ограничения: лишние символы не должны ронять вебхук
    ig_account_id: Mapped[str] = mapped_column(Text)
    # comment, message, postback, read
    kind: Mapped[str] = mapped_column(String(16))
    # Meta повторяет вебхуки: id коммента или mid сообщения, второй раз не ляжет
    dedup_key: Mapped[str] = mapped_column(String(128), unique=True)
    # одно событие как прислала Meta: changes[].value или messaging[]
    payload: Mapped[dict] = mapped_column(JSONB)
    # id запроса вебхука: worker поднимает его в логи, цепочка читается по одному id
    request_id: Mapped[str | None] = mapped_column(String(64))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # done: разобрано; skipped: не для нас (чужой аккаунт, свой коммент); failed: сдались
    outcome: Mapped[str | None] = mapped_column(String(16))
    # почему skipped или почему падало: наш код причины или имя класса ошибки.
    # Текст ошибки не храним: в нём бывают куски payload с личными данными
    reason: Mapped[str | None] = mapped_column(String(64))
    # кто взял событие себе: имя модуля от worker. Пусто: никто (ни один
    # автоответ не подошёл) или событие никому не нужно
    handled_by: Mapped[str | None] = mapped_column(String(32))
    # сколько раз worker брался и падал; после 5 outcome = failed
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # упавшее не берём раньше этого времени, пауза растёт с attempts
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Account(Base):
    """Подключённый аккаунт Instagram. Принадлежит установке, а не пользователю:
    connected_by только помнит, кто подключал. После отключения строка остаётся,
    по ней журнал и статистика знают, чей это был аккаунт."""

    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'token_expired', 'disconnected')", name="status_known"
        ),
        # активному аккаунту без токена нечем отвечать: база такого не допускает
        CheckConstraint(
            "status <> 'active' OR token_encrypted IS NOT NULL", name="active_has_token"
        ),
        {"schema": "instagram"},
    )
    # даты считает база: забираем их RETURNING-ом сразу после INSERT и UPDATE
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # id аккаунта в Instagram: он же entry[].id в вебхуках. Повторный вход оживляет строку
    ig_user_id: Mapped[str] = mapped_column(Text, unique=True)
    # ник меняется: обновляем при каждом входе, для людей, не для связей
    username: Mapped[str] = mapped_column(Text)
    # долгий токен, зашифрован core.crypto. Пусто после отключения
    token_encrypted: Mapped[str | None]
    # токен живёт 60 дней; worker обновляет его заранее, иначе только новый вход
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active")
    # кто подключал: id из identity, без внешнего ключа на чужую схему
    connected_by: Mapped[uuid.UUID]
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxTask(Base):
    """Исходящее в Meta: Private Reply, сообщение или ответ под комментом. Кладут
    той же транзакцией, что и решение, отправляет worker. Сеть только здесь."""

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("kind IN ('private_reply', 'message', 'comment_reply')", name="kind_known"),
        CheckConstraint("outcome IN ('sent', 'failed', 'expired')", name="outcome_known"),
        # итог есть ровно у завершённой задачи
        CheckConstraint("(finished_at IS NULL) = (outcome IS NULL)", name="outcome_when_finished"),
        # очередь worker: незавершённые по времени, завершённые индекс не раздувают
        Index("ix_outbox_due", "run_at", postgresql_where=text("outcome IS NULL")),
        # отчёты, которые не дошли: подборщик ищет их по этому индексу. Брошенные
        # после MAX_ATTEMPTS (5) в него не входят
        Index(
            "ix_outbox_unreported",
            "finished_at",
            postgresql_where=text(
                "outcome IS NOT NULL AND ref IS NOT NULL AND reported_at IS NULL"
                " AND report_attempts < 5"
            ),
        ),
        # лимит 750 Private Reply в час на аккаунт считается по этому индексу
        Index(
            "ix_outbox_private_replies_sent",
            "account_id",
            "finished_at",
            postgresql_where=text("kind = 'private_reply' AND outcome = 'sent'"),
        ),
        {"schema": "instagram"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Account.id))
    kind: Mapped[str] = mapped_column(String(16))
    # кому и что: comment_id или recipient_id, text, button {title, payload}
    payload: Mapped[dict] = mapped_column(JSONB)
    # метка вызывающего («autoreplies:<id выдачи>»): instagram её не читает,
    # только возвращает с итогом отправки
    ref: Mapped[str | None] = mapped_column(String(128))
    # один Private Reply на коммент, одно сообщение на нажатие: второй не ляжет
    dedup_key: Mapped[str] = mapped_column(String(128), unique=True)
    # раньше не отправлять: перенос по лимиту и пауза между повторами
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # позже Meta не примет: Private Reply 7 дней от коммента, сообщение 24 часа
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # sent, failed, expired
    outcome: Mapped[str | None] = mapped_column(String(16))
    # код ошибки Meta или имя класса ошибки, без текста
    reason: Mapped[str | None] = mapped_column(String(64))
    # какой вариант письма ушёл: following, not_following, unknown. Хранится,
    # чтобы отчёт можно было повторить
    variant: Mapped[str | None] = mapped_column(String(16))
    # итог принял тот, кто ставил письмо (по ref). У завершённой с ref пусто:
    # отчёт не дошёл, worker его повторит
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # сколько раз отчёт падал; после 5 worker его бросает
    report_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # раньше отчёт не повторять: пауза после неудачи
    report_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # id запроса вебхука, из-за которого задача появилась: логи склеиваются
    request_id: Mapped[str | None] = mapped_column(String(64))
