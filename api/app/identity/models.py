"""Таблицы identity. Снаружи модуля не импортируются, соседям отдаём справки."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'member')", name="role_known"),
        # владелец у установки ровно один, это держит база, а не только код
        Index("one_owner", "role", unique=True, postgresql_where=text("role = 'owner'")),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # храним в нижнем регистре, приводит сервис
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(String(16))
    # участник с этим правом может подключать аккаунты Instagram
    can_connect_accounts: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginSession(Base):
    __tablename__ = "login_session"
    __table_args__ = {"schema": "identity"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # индекс: «выйти везде» и каскадное удаление ищут сессии по пользователю
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.user.id", ondelete="CASCADE"), index=True
    )
    # SHA-256 от токена в hex, сам токен есть только у клиента
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # скользящий срок: при использовании продлевается, но не чаще раза в сутки
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
