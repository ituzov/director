import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from app.identity import repository, service
from app.identity.exceptions import InvalidCredentials
from app.identity.models import LoginSession
from app.identity.passwords import hash_password, needs_rehash

T0 = datetime(2026, 1, 1, tzinfo=UTC)
PASSWORD = "password1"


@pytest.fixture
async def user(session):
    user = repository.add_user(
        session, email="owner@example.com", password_hash=hash_password(PASSWORD), role="owner"
    )
    await session.commit()
    return user


async def login(session, *, email="owner@example.com", password=PASSWORD, now=T0):
    return await service.login(session, email=email, password=password, now=now)


async def test_token_identifies_user(session, user):
    token = await login(session, email="  OWNER@example.com")
    assert await service.user_by_token(session, token, now=T0) == user


async def test_wrong_password(session, user):
    with pytest.raises(InvalidCredentials):
        await login(session, password="wrong-password")


async def test_unknown_email_same_error(session, user):
    with pytest.raises(InvalidCredentials):
        await login(session, email="nobody@example.com")


async def test_unknown_token(session, user):
    assert await service.user_by_token(session, "nope", now=T0) is None


async def test_only_hash_stored(session, user):
    token = await login(session)
    stored = await session.scalar(select(LoginSession.token_hash))
    assert stored != token
    assert stored == hashlib.sha256(token.encode()).hexdigest()


async def test_session_expires(session, user):
    token = await login(session)
    assert await service.user_by_token(session, token, now=T0 + timedelta(days=31)) is None


async def test_used_session_slides(session, user):
    token = await login(session)
    assert await service.user_by_token(session, token, now=T0 + timedelta(days=2)) == user
    # продлилась на 30 дней от второго дня, поэтому на 31-й ещё жива
    assert await service.user_by_token(session, token, now=T0 + timedelta(days=31)) == user


async def test_no_renew_within_a_day(session, user):
    token = await login(session)
    await service.user_by_token(session, token, now=T0 + timedelta(hours=12))
    stored = await session.scalar(select(LoginSession.expires_at))
    assert stored == T0 + service.SESSION_TTL


async def test_logout(session, user):
    token = await login(session)
    await service.logout(session, token)
    assert await service.user_by_token(session, token, now=T0) is None
    await service.logout(session, token)  # повторный выход не падает


async def test_old_hash_upgraded_on_login(session):
    weak = PasswordHasher(time_cost=1).hash(PASSWORD)
    user = repository.add_user(session, email="old@example.com", password_hash=weak, role="owner")
    await session.commit()

    await login(session, email="old@example.com")
    assert user.password_hash != weak
    assert not needs_rehash(user.password_hash)
