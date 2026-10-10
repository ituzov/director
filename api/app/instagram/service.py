"""Сценарии instagram. Одна функция это одна операция и один commit."""

import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.instagram import repository
from app.instagram.exceptions import AppSecretRequired
from app.instagram.models import MetaApp


async def get_meta_app(session: AsyncSession) -> MetaApp | None:
    return await repository.get_meta_app(session)


async def save_meta_app(session: AsyncSession, *, app_id: str, app_secret: str | None) -> MetaApp:
    """Сохранить ключи приложения. Секрет None значит «не менять»."""
    meta_app = await repository.get_meta_app(session)
    if meta_app is None:
        if app_secret is None:
            raise AppSecretRequired
        meta_app = repository.add_meta_app(
            session,
            app_id=app_id,
            app_secret_encrypted=crypto.encrypt(app_secret),
            # hex, а не urlsafe: без - и _ слово целиком выделяется двойным кликом
            verify_token=secrets.token_hex(16),
        )
    else:
        meta_app.app_id = app_id
        if app_secret is not None:
            meta_app.app_secret_encrypted = crypto.encrypt(app_secret)
        # verify_token не трогаем: он уже прописан в Meta, новый сломает вебхук

    try:
        await session.commit()
    except IntegrityError:
        # два первых сохранения разом: строку вставил соседний запрос, обновим её
        await session.rollback()
        return await save_meta_app(session, app_id=app_id, app_secret=app_secret)
    return meta_app
