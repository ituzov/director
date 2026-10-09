"""Окружение Alembic: к какой базе подключаться и с какими моделями сравнивать.

Адрес базы берём из settings, а не из конфига Alembic: он один на всё
приложение и в разработке, и в compose.
"""

import asyncio
import logging

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.db_models  # noqa: F401  импорт регистрирует модели в Base.metadata
from alembic import context
from app.config import settings
from app.db import SCHEMAS, Base

# alembic.ini нет, поэтому логи настраиваем сами: видно, какие миграции применились
logging.basicConfig(format="%(levelname)-5.5s [%(name)s] %(message)s", level=logging.WARNING)
logging.getLogger("alembic").setLevel(logging.INFO)


def include_name(name, type_, parent_names) -> bool:
    """Смотрим только на свои схемы.

    Без include_schemas autogenerate не видит ничего вне public, а с ним
    видит все схемы базы и предлагает снести то, чего нет в моделях.
    None это public: если модель забыли привязать к схеме, она всплывёт там.
    """
    if type_ == "schema":
        return name is None or name in SCHEMAS
    return True


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations() -> None:
    # NullPool: Alembic подключается один раз, пул ему не нужен
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


asyncio.run(run_migrations())
