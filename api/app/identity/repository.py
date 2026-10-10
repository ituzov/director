"""Запросы identity к базе. Без бизнес-правил и без commit: транзакцией
владеет сервис."""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User


async def owner_exists(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(exists().where(User.role == "owner"))))


def add_user(session: AsyncSession, *, email: str, password_hash: str, role: str) -> User:
    user = User(email=email, password_hash=password_hash, role=role)
    session.add(user)
    return user
