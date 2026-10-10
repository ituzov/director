"""Запросы identity к базе. Без бизнес-правил и без commit: транзакцией
владеет сервис."""

import uuid
from datetime import datetime

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import LoginSession, User


async def owner_exists(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(exists().where(User.role == "owner"))))


def add_user(session: AsyncSession, *, email: str, password_hash: str, role: str) -> User:
    user = User(email=email, password_hash=password_hash, role=role)
    session.add(user)
    return user


async def user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


def add_login_session(
    session: AsyncSession, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime
) -> LoginSession:
    login_session = LoginSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(login_session)
    return login_session


async def login_session_with_user(
    session: AsyncSession, token_hash: str
) -> tuple[LoginSession, User] | None:
    # Row в SQLAlchemy 2.1 сам ведёт себя как кортеж, распаковывается напрямую
    return (
        await session.execute(
            select(LoginSession, User)
            .join(User, LoginSession.user_id == User.id)
            .where(LoginSession.token_hash == token_hash)
        )
    ).first()


async def delete_login_session(session: AsyncSession, token_hash: str) -> None:
    await session.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash))
