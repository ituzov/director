"""Тесты на настоящем Postgres.

База director_test пересоздаётся на каждый прогон, миграции проходят полный
круг: вверх, вниз до нуля и снова вверх. Так прогон заодно проверяет, что
миграции ложатся на пустую базу и откатываются, а откат нужен апдейтеру.

Каждый тест живёт в транзакции, которая в конце откатывается: commit() в коде
становится savepoint. Чистить таблицы не нужно, мусор не остаётся даже
после прерванного прогона.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.logging import setup_logging
from app.db import get_session
from app.identity import repository as identity_repository
from app.identity import service as identity_service
from app.identity.passwords import hash_password
from app.main import app

# api/: здесь pyproject.toml с конфигом alembic
API_DIR = Path(__file__).parent.parent

# Та же dev-Postgres, база с суффиксом _test. Переопределяется TEST_DATABASE_URL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", settings.database_url.rsplit("/", 1)[0] + "/director_test"
)


def _alembic(*args: str) -> None:
    # Отдельным процессом: env.py читает настройки при импорте, адрес
    # подменяем переменной окружения. sys.executable, чтобы работало и без uv
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        cwd=API_DIR,  # alembic ищет конфиг в текущей папке
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} упал:\n{result.stderr}")


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Пересоздать базу и прогнать миграции туда и обратно. Раз за прогон."""
    # База дропается целиком, поэтому только та, что явно тестовая
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    if not db_name.endswith("_test"):
        raise RuntimeError(f"Тестовая база должна кончаться на _test, а не {db_name}")

    server = TEST_DATABASE_URL.replace("+psycopg", "").rsplit("/", 1)[0]
    with psycopg.connect(f"{server}/postgres", autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{db_name}"')

    _alembic("upgrade", "head")
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")


@pytest.fixture
async def session():
    """Сессия в песочнице: всё, что тест запишет, откатится после него.

    Обычно сессия сама берёт подключение и сама делает BEGIN и COMMIT.
    Здесь мы заранее открываем подключение и транзакцию и вручаем их ей.
    Её commit() становится savepoint внутри нашей транзакции, а настоящего
    COMMIT не бывает вовсе. После теста откатываем транзакцию целиком.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()  # BEGIN: черновик на весь тест
        async with AsyncSession(
            bind=conn,  # работай в нашем подключении, а значит в нашем черновике
            # транзакция уже открыта: свои commit/rollback делай savepoint-ами
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,  # как в app/db.py
        ) as s:
            yield s  # здесь выполняется тест
        await outer.rollback()  # ROLLBACK: выбрасываем всё, что тест записал
    await engine.dispose()


@pytest.fixture
async def client(session):
    """HTTP-клиент к приложению в той же песочнице: ручки получают нашу сессию."""
    app.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def login_as(session):
    """Завести пользователя с ролью и войти. Отдаёт заголовок с токеном."""

    async def login(role: str) -> dict[str, str]:
        email = f"{role}@test.dev"
        identity_repository.add_user(
            session, email=email, password_hash=hash_password("password1"), role=role
        )
        await session.commit()
        token = await identity_service.login(session, email=email, password="password1")
        return {"Authorization": f"Bearer {token}"}

    return login


@pytest.fixture
def real_logging():
    """Настоящая цепочка логов в JSON на время теста, потом прежние обработчики.
    Читать вывод через capsys.readouterr().err."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield lambda: setup_logging("INFO", json=True)
    root.handlers, root.level = handlers, level
