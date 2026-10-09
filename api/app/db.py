"""Подключение к базе: async-движок, фабрика сессий, базовый класс моделей.

Инфраструктурный слой. Сессию получают репозитории, сервисы и роуты
к движку напрямую не обращаются.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Схема Postgres на каждый модуль: владелец таблицы виден прямо в базе.
# Отсюда env.py Alembic берёт, какие схемы считать своими
SCHEMAS = ("identity", "instagram", "campaigns", "updates", "core")

# psycopg 3 в одном URL умеет и sync, и async, async-движок берёт async-режим
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Базовый класс всех ORM-моделей."""


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Сессия на запрос. Commit делает инициатор операции (сервис),
    здесь только откат при необработанной ошибке."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]
