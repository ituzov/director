"""Сценарии identity. Одна функция это одна операция и один commit."""

import hmac

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.identity import repository
from app.identity.exceptions import (
    InvalidSetupToken,
    OwnerAlreadyExists,
    SetupDisabled,
    WeakPassword,
)
from app.identity.models import User
from app.identity.passwords import hash_password

MIN_PASSWORD_LENGTH = 8


def _check_setup_token(token: str) -> None:
    if settings.setup_token is None:
        raise SetupDisabled
    # время сравнения не зависит от того, где расхождение: посимвольно не подобрать
    if not hmac.compare_digest(token.encode(), settings.setup_token.encode()):
        raise InvalidSetupToken


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
