"""Сценарии instagram. Одна функция это одна операция и один commit."""

import secrets
import ssl
from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy import func
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
        meta_app.updated_at = func.now()

    try:
        await session.commit()
    except IntegrityError:
        # два первых сохранения разом: строку вставил соседний запрос, обновим её
        await session.rollback()
        return await save_meta_app(session, app_id=app_id, app_secret=app_secret)
    # app_id не секрет, сам секрет в лог не идёт: только факт замены
    log.info("meta_app.saved", app_id=app_id, first=first, secret_replaced=app_secret is not None)
    return meta_app


# Meta проверяет адрес с mode=subscribe, самопроверка админки с mode=check.
# Подделать subscribe нельзя: без маркера успеха нет, а маркер знают только Meta и мы
META_MODE = "subscribe"
CHECK_MODE = "check"


async def verify_webhook(session: AsyncSession, *, mode: str | None, token: str | None) -> bool:
    """Проверка адреса вебхука: от Meta из кабинета или самопроверка админки."""
    meta_app = await repository.get_meta_app(session)
    if meta_app is None:
        reason = "no_app"
    elif mode not in (META_MODE, CHECK_MODE):
        reason = "bad_mode"
    # сравнение за постоянное время: по скорости ответа маркер не подобрать
    elif token is None or not secrets.compare_digest(token, meta_app.verify_token):
        reason = "bad_token"
    else:
        if mode == META_MODE:
            meta_app.webhook_verified_at = datetime.now(UTC)
            await session.commit()
        log.info("webhook.verified", mode=mode)
        return True
    log.warning("webhook.verify_failed", reason=reason)
    return False


# Meta ждёт ответа вебхука несколько секунд; дольше, значит что-то не так
CHECK_TIMEOUT = 10.0


def _http() -> httpx.AsyncClient:
    # в тестах подменяется: в сеть тесты не ходят
    return httpx.AsyncClient(timeout=CHECK_TIMEOUT)


def _is_tls_error(exc: BaseException) -> bool:
    # httpx заворачивает ошибку сертификата в ConnectError, сама она глубже в цепочке
    while exc is not None:
        if isinstance(exc, ssl.SSLError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


async def check_webhook(session: AsyncSession) -> str | None:
    """Самопроверка из админки: api идёт на свой публичный адрес вебхука тем же
    путём, что Meta (DNS, HTTPS, Caddy, ручка). None, если адрес отвечает, иначе
    код ошибки: no_app, no_public_url, timeout, tls, unreachable, bad_status, bad_body."""
    meta_app = await repository.get_meta_app(session)
    url = public_url(WEBHOOK_PATH)
    if meta_app is None:
        error = "no_app"
    elif url is None:
        error = "no_public_url"
    else:
        challenge = str(secrets.randbelow(10**9))
        params = {
            "hub.mode": CHECK_MODE,
            "hub.verify_token": meta_app.verify_token,
            "hub.challenge": challenge,
        }
        try:
            async with _http() as client:
                response = await client.get(url, params=params)
        except httpx.TimeoutException:
            error = "timeout"
        except httpx.HTTPError as exc:
            error = "tls" if _is_tls_error(exc) else "unreachable"
        else:
            if response.status_code != 200:
                error = "bad_status"
            elif response.text != challenge:
                error = "bad_body"
            else:
                error = None
    # адрес в лог не идёт: в нём маркер
    if error is None:
        log.info("webhook.check_passed")
    else:
        log.warning("webhook.check_failed", error=error)
    return error
