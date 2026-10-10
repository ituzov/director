"""Модель User: ограничения держит база, а не только код.

Заодно проверяет механику conftest: commit() внутри теста не выходит
за пределы его транзакции.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.identity.models import User
from tests.conftest import TEST_DATABASE_URL


def make_user(email: str, role: str = "member") -> User:
    return User(email=email, password_hash="x", role=role)


async def test_second_owner_rejected(session):
    session.add(make_user("owner@test.dev", role="owner"))
    await session.commit()

    session.add(make_user("other@test.dev", role="owner"))
    with pytest.raises(IntegrityError, match="one_owner"):
        await session.commit()


async def test_unknown_role_rejected(session):
    session.add(make_user("admin@test.dev", role="admin"))
    with pytest.raises(IntegrityError, match="ck_user_role_known"):
        await session.commit()


async def test_commit_stays_inside_test(session):
    """Тест закоммитил, но снаружи его транзакции строки не видно:
    после теста она откатится вместе со всем остальным."""
    session.add(make_user("member@test.dev"))
    await session.commit()
    assert await session.scalar(select(func.count()).select_from(User)) == 1

    outside = create_async_engine(TEST_DATABASE_URL)
    async with outside.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(User)) == 0
    await outside.dispose()
