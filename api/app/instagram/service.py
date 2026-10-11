"""Сценарии instagram. Одна функция это одна операция и один commit."""

import secrets

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import crypto
from app.instagram import repository
from app.instagram.exceptions import AppSecretRequired
from app.instagram.models import MetaApp

# имя логгера постоянное, по нему ищут в логах: при переезде файла не меняется
log = structlog.get_logger("app.instagram")

# Пути, которые владелец прописывает в кабинете Meta. Поменять путь значит
# заставить каждого владельца перенастроить приложение, поэтому они постоянные
WEBHOOK_PATH = "/webhooks/instagram"
OAUTH_CALLBACK_PATH = "/instagram/callback"
PRIVACY_PATH = "/privacy"


def public_url(path: str) -> str | None:
    """Полный адрес на этом сервере. None, пока адрес сервера не задан."""
    if not settings.public_url:
        return None
    return settings.public_url.rstrip("/") + path


async def get_meta_app(session: AsyncSession) -> MetaApp | None:
    return await repository.get_meta_app(session)


async def save_meta_app(session: AsyncSession, *, app_id: str, app_secret: str | None) -> MetaApp:
    """Сохранить ключи приложения. Секрет None значит «не менять»."""
    meta_app = await repository.get_meta_app(session)
    first = meta_app is None
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
    # app_id не секрет, сам секрет в лог не идёт: только факт замены
    log.info("meta_app.saved", app_id=app_id, first=first, secret_replaced=app_secret is not None)
    return meta_app


async def verify_webhook(session: AsyncSession, *, mode: str | None, token: str | None) -> bool:
    """Проверка адреса вебхука из кабинета Meta: подписка и наш маркер."""
    meta_app = await repository.get_meta_app(session)
    if meta_app is None:
        reason = "no_app"
    elif mode != "subscribe":
        reason = "bad_mode"
    # сравнение за постоянное время: по скорости ответа маркер не подобрать
    elif token is None or not secrets.compare_digest(token, meta_app.verify_token):
        reason = "bad_token"
    else:
        log.info("webhook.verified")
        return True
    log.warning("webhook.verify_failed", reason=reason)
    return False
