"""Таблицы instagram. Снаружи модуля не импортируются, соседям отдаём справки."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, String, func
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

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    # Instagram App ID, не секрет: он виден в адресе OAuth
    app_id: Mapped[str] = mapped_column(String(32))
    # Instagram App Secret, зашифрован core.crypto. Им же подписаны вебхуки
    app_secret_encrypted: Mapped[str]
    # пароль проверки адреса вебхука: генерирует Директор, владелец копирует в Meta
    verify_token: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
