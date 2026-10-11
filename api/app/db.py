"""Подключение к базе: async-движок, фабрика сессий, базовый класс моделей.

Инфраструктурный слой. Сессию получают репозитории, сервисы и роуты
к движку напрямую не обращаются.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Схема Postgres на каждый модуль: владелец таблицы виден прямо в базе.
# Отсюда env.py Alembic берёт, какие схемы считать своими
SCHEMAS = ("identity", "instagram", "campaigns", "updates", "activity", "core")

# psycopg 3 в одном URL умеет и sync, и async, async-движок берёт async-режим


def make_engine(url: str, **options):
    """Движок с нашими правилами. Один на приложение, тесты строят свой так же."""
    # hide_parameters: значения запроса не попадают в текст ошибки, а там бывают
    # токены и тела вебхуков. Сам запрос в ошибке остаётся
    return create_async_engine(url, hide_parameters=True, **options)


engine = make_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Базовый класс всех ORM-моделей."""

    # Предсказуемые имена ограничений: миграции находят их по имени.
    # Задаётся до первой миграции, потом менять больно
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


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
