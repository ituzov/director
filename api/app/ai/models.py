"""Таблицы ai. Снаружи модуля не импортируются, соседям отдаём справки."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Connection(Base):
    """Ключ к провайдеру моделей. Их несколько сразу: задача выбирает, через какой
    идти. Провайдер сверяем с реестром в коде, а не CHECK в базе: новый провайдер
    не должен тянуть за собой миграцию."""

    __tablename__ = "connection"
    __table_args__ = (
        # ошибка записана целиком или её нет: код без времени не сравнить с вызовом
        CheckConstraint("(error_code IS NULL) = (error_at IS NULL)", name="error_complete"),
        {"schema": "ai"},
    )
    # даты считает база: забираем их RETURNING-ом сразу после INSERT и UPDATE
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # вид из реестра провайдеров: anthropic, timeweb
    provider: Mapped[str] = mapped_column(String(32))
    # для людей: два ключа одного провайдера различают по имени
    name: Mapped[str] = mapped_column(Text)
    # ключ провайдера, зашифрован core.crypto
    key_encrypted: Mapped[str]
    # последние символы ключа для экрана, чтобы не расшифровывать ради показа
    key_hint: Mapped[str] = mapped_column(String(8))
    # свой адрес для OpenAI-совместимых; у известных провайдеров адрес в профиле
    base_url: Mapped[str | None] = mapped_column(Text)
    # когда меняли ключ. Ошибку пишет только вызов, начатый позже: 401 от старого
    # ключа, долетевший после замены, не краснит новый
    key_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # когда ключ последний раз прошёл проверку; пусто, если проверка не дождалась ответа
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # последняя ошибка, которая значит «само не пройдёт»: ключ не принят, нет денег.
    # Разовые 5xx и таймауты сюда не пишем, они только в журнале вызовов
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # кто подключал: id из identity, без внешнего ключа на чужую схему
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Binding(Base):
    """Какая задача через какое подключение и модель идёт. Живёт в ai, а не у задачи:
    ai ниже ассистента и автоответов и спросить их не может, а «задачи на нём»
    нужны на карточке подключения."""

    __tablename__ = "binding"
    __table_args__ = (
        # у задачи одна модель на область; пустая область тоже одна
        Index(
            "uq_binding_purpose_scope",
            "purpose",
            "scope",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_binding_connection", "connection_id"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # что за задача: assistant.route, assistant.answer, autoreplies.suggest.
    # Название для людей подставляет web по этому ключу
    purpose: Mapped[str] = mapped_column(String(64))
    # чья задача: id аккаунта у ассистента, пусто у задач на всю установку
    scope: Mapped[str | None] = mapped_column(Text)
    # удалили подключение: задача остаётся и показывает «не настроено»
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(Connection.id, ondelete="SET NULL")
    )
    # id модели как у провайдера: claude-haiku-5-5, anthropic/claude-haiku-5-5
    model: Mapped[str] = mapped_column(Text)
    # провайдер ответил, что модели нет: пометка у задачи, а не у ключа
    model_missing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Call(Base):
    """Журнал вызовов модели: кто, через что, сколько токенов, чем кончилось. Текст
    запроса и ответа не храним: там комменты людей. По журналу ассистент считает
    свой суточный предохранитель."""

    __tablename__ = "call"
    __table_args__ = (
        CheckConstraint("outcome IN ('ok', 'error')", name="outcome_known"),
        CheckConstraint("(outcome = 'error') = (error_code IS NOT NULL)", name="error_when_failed"),
        # предохранитель: вызовы задачи за сутки
        Index("ix_call_purpose_started", "purpose", "started_at"),
        # удаление подключения обнуляет ссылку в журнале: без индекса это проход
        # по всему журналу под замком подключения
        Index("ix_call_connection", "connection_id"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # когда начали, а не кончили: с этим сравниваем key_changed_at и error_at
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str | None] = mapped_column(Text)
    # подключение могли удалить, а строка журнала остаётся: провайдер и модель копией
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(Connection.id, ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(Text)
    # токены как их посчитал провайдер; при ошибке их может не быть
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(8))
    # наш код ошибки, не провайдера: key_rejected, no_funds, model_missing, timeout, server
    error_code: Mapped[str | None] = mapped_column(String(32))
    # HTTP-статус ответа, если до него дошло: для разбора, решения по нему не принимаем
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
