"""Сценарии identity. Одна функция это одна операция и один commit."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.identity import repository
from app.identity.exceptions import (
    InvalidCredentials,
    InvalidSetupToken,
    OwnerAlreadyExists,
    SetupDisabled,
    WeakPassword,
)
from app.identity.models import User
from app.identity.passwords import hash_password, needs_rehash, verify_password

MIN_PASSWORD_LENGTH = 8
SESSION_TTL = timedelta(days=30)
# продлеваем не чаще раза в сутки, чтобы не писать в базу на каждый запрос
SESSION_RENEW_AFTER = timedelta(days=1)

# хеш-пустышка: на несуществующую почту тратим столько же времени, сколько на настоящую
_DUMMY_HASH = hash_password("dummy-password")


def _check_setup_token(token: str) -> None:
    if settings.setup_token is None:
        raise SetupDisabled
    # время сравнения не зависит от того, где расхождение: посимвольно не подобрать
    if not hmac.compare_digest(token.encode(), settings.setup_token.encode()):
        raise InvalidSetupToken


async def setup_needed(session: AsyncSession) -> bool:
    return not await repository.owner_exists(session)


async def register_owner(session: AsyncSession, *, token: str, email: str, password: str) -> User:
    _check_setup_token(token)
    if await repository.owner_exists(session):
        raise OwnerAlreadyExists
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword

    user = repository.add_user(
        session,
        email=email.strip().lower(),
        password_hash=hash_password(password),
        role="owner",
    )
    try:
        await session.commit()
    except IntegrityError as e:
        # два setup одновременно: проверку выше прошли оба, второго остановил one_owner
        await session.rollback()
        raise OwnerAlreadyExists from e
    return user


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def login(
    session: AsyncSession, *, email: str, password: str, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    user = await repository.user_by_email(session, email.strip().lower())
    if user is None:
        verify_password(_DUMMY_HASH, password)
        raise InvalidCredentials
    if not verify_password(user.password_hash, password):
        raise InvalidCredentials
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    token = secrets.token_urlsafe(32)
    repository.add_login_session(
        session, user_id=user.id, token_hash=_hash_token(token), expires_at=now + SESSION_TTL
    )
    await session.commit()
    return token


async def user_by_token(
    session: AsyncSession, token: str, *, now: datetime | None = None
) -> User | None:
    now = now or datetime.now(UTC)
    found = await repository.login_session_with_user(session, _hash_token(token))
    if found is None:
        return None
    login_session, user = found
    if login_session.expires_at <= now:
        return None
    # срок продлевали больше суток назад: двигаем на полные 30 дней от сейчас
    if login_session.expires_at - now < SESSION_TTL - SESSION_RENEW_AFTER:
        login_session.expires_at = now + SESSION_TTL
        await session.commit()
    return user


async def logout(session: AsyncSession, token: str) -> None:
    await repository.delete_login_session(session, _hash_token(token))
    await session.commit()
