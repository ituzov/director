"""Подключения к провайдерам моделей: сохранить ключ с проверкой, заменить,
переименовать, проверить ещё раз, удалить.

Сеть идёт до записи в базу и вне транзакции: пока провайдер думает (до
CHECK_TIMEOUT), ни одна строка не заперта. Ключ в логи не попадает, даже
последними символами.
"""

import uuid
from datetime import UTC, datetime

import httpx2
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import providers, repository
from app.ai.exceptions import (
    BaseUrlNotAllowed,
    BaseUrlRequired,
    ConnectionNotFound,
    KeyRejected,
    KeyTooShort,
    ModelRequired,
    UnknownProvider,
)
from app.ai.models import Connection
from app.ai.providers.base import KEY_REJECTED, NO_FUNDS, Provider, ProviderError
from app.core import crypto

log = structlog.get_logger("app.ai")

# ключ не расшифровать: сменился SECRET_KEY, владелец вводит ключ заново
KEY_UNREADABLE = "key_unreadable"
# ошибки, которые сами не пройдут: их показывает карточка подключения. Разовые
# сбои (таймаут, 5xx, лимит провайдера) карточку не трогают
CARD_ERRORS = frozenset({KEY_REJECTED, NO_FUNDS, KEY_UNREADABLE})

# проверка ключа это один бесплатный запрос; дольше, значит провайдеру плохо
CHECK_TIMEOUT = 15.0
# настоящие ключи длиной в десятки символов; у короткого последние 4 это много
MIN_KEY = 20
HINT = 4


def _http() -> httpx2.AsyncClient:
    # один клиент на проверку; тесты подменяют эту функцию
    return httpx2.AsyncClient(timeout=CHECK_TIMEOUT)


def _now() -> datetime:
    return datetime.now(UTC)


def _provider(kind: str) -> Provider:
    provider = providers.get(kind)
    if provider is None:
        raise UnknownProvider
    return provider


def _base_url(provider: Provider, base_url: str | None) -> str | None:
    base_url = (base_url or "").strip() or None
    if provider.needs_base_url and base_url is None:
        raise BaseUrlRequired
    # на этот адрес уйдёт ключ: у известного провайдера свой адрес не принимаем
    if not provider.needs_base_url and base_url is not None:
        raise BaseUrlNotAllowed
    return base_url


def _key(key: str) -> str:
    key = key.strip()
    if len(key) < MIN_KEY:
        raise KeyTooShort
    return key


async def _check(provider: Provider, *, key: str, base_url: str | None) -> str | None:
    """Пробный запрос. None: ключ работает. Иначе наш код ошибки."""
    try:
        async with _http() as http:
            await provider.check_key(http, key=key, base_url=base_url)
    except ProviderError as error:
        log.warning(
            "ai.connection.check_failed",
            provider=provider.kind,
            code=error.code,
            http_status=error.http_status,
        )
        return error.code
    return None


def apply_result(
    connection: Connection, *, key_changed_at: datetime, started: datetime, code: str | None
) -> None:
    """Итог проверки или вызова на карточку подключения. Одно правило для всех:
    итог про тот ключ, что сейчас в базе, и не старше уже записанного. Успех
    ставит «проверен» и снимает ошибку, поломка наоборот. Разовый сбой (таймаут,
    5xx, лимит провайдера) ничего не говорит о ключе и карточку не трогает."""
    # ключ заменили, пока шёл вызов или проверка: итог про старый ключ
    if connection.key_changed_at != key_changed_at:
        return
    if code is not None and code not in CARD_ERRORS:
        return
    latest = max((t for t in (connection.checked_at, connection.error_at) if t), default=None)
    # на карточке уже итог вызова, начатого позже этого
    if latest is not None and started < latest:
        return
    if code is None:
        connection.checked_at, connection.error_code, connection.error_at = started, None, None
    else:
        connection.checked_at, connection.error_code, connection.error_at = None, code, started


def _new_key(connection: Connection, key: str) -> None:
    """Новый ключ: всё, что знали про старый, к нему не относится."""
    connection.key_encrypted = crypto.encrypt(key)
    connection.key_hint = key[-HINT:]
    # время записи, а не начала проверки: вызов, начатый пока проверяли, шёл
    # ещё со старым ключом, и его итог не должен лечь на новый
    connection.key_changed_at = _now()
    connection.checked_at, connection.error_code, connection.error_at = None, None, None


async def list_connections(session: AsyncSession) -> list[Connection]:
    return await repository.list_connections(session)


async def create_connection(
    session: AsyncSession,
    *,
    provider: str,
    name: str,
    key: str,
    base_url: str | None,
    created_by: uuid.UUID,
) -> Connection:
    """Сохранить ключ. Ключ, который провайдер не принял, не сохраняем: он не
    заработает, а владелец скорее скопировал его не целиком. Остальное сохраняем:
    нет денег чинится пополнением, сбой пройдёт сам."""
    profile = _provider(provider)
    base_url = _base_url(profile, base_url)
    key = _key(key)
    started = _now()
    error = await _check(profile, key=key, base_url=base_url)
    if error == KEY_REJECTED:
        raise KeyRejected
    connection = repository.add_connection(
        session,
        provider=profile.kind,
        name=name.strip() or profile.kind,
        key_encrypted="",
        key_hint="",
        base_url=base_url,
        key_changed_at=started,
        checked_at=None,
        error_code=None,
        error_at=None,
        created_by=created_by,
    )
    _new_key(connection, key)
    apply_result(connection, key_changed_at=connection.key_changed_at, started=started, code=error)
    await session.commit()
    log.info(
        "ai.connection.created",
        connection_id=str(connection.id),
        provider=profile.kind,
        checked=connection.checked_at is not None,
        error_code=connection.error_code,
    )
    return connection


async def replace_key(session: AsyncSession, connection_id: uuid.UUID, *, key: str) -> Connection:
    """Новый ключ вместо старого, с той же проверкой. key_changed_at сдвигается:
    401 от старого ключа, долетевший после замены, новый не окрасит."""
    connection = await _get(session, connection_id)
    profile = _provider(connection.provider)
    base_url = connection.base_url
    key = _key(key)
    # сеть вне транзакции: прочитанное выше не держим, после проверки перечитаем
    await session.rollback()
    started = _now()
    error = await _check(profile, key=key, base_url=base_url)
    if error == KEY_REJECTED:
        raise KeyRejected
    # подключение могли удалить, пока шла проверка: тогда не создаём его заново
    connection = await _get(session, connection_id, lock=True)
    _new_key(connection, key)
    apply_result(connection, key_changed_at=connection.key_changed_at, started=started, code=error)
    await session.commit()
    log.info(
        "ai.connection.key_replaced",
        connection_id=str(connection_id),
        checked=connection.checked_at is not None,
        error_code=connection.error_code,
    )
    return connection


async def recheck(session: AsyncSession, connection_id: uuid.UUID) -> Connection:
    """«Проверить ещё раз»: пополнил баланс или ключ поменяли в панели провайдера.
    Ключ не принят здесь пишется на карточку, а не бросается: ключ уже сохранён."""
    connection = await _get(session, connection_id)
    profile = _provider(connection.provider)
    base_url = connection.base_url
    changed_at = connection.key_changed_at
    try:
        key = crypto.decrypt(connection.key_encrypted)
    except crypto.DecryptError:
        # читали без замка: перечитываем под замком, сверка отпечатка в apply_result.
        # Удалили между чтением и записью: ConnectionNotFound, а не StaleDataError
        connection = await _get(session, connection_id, lock=True)
        apply_result(connection, key_changed_at=changed_at, started=_now(), code=KEY_UNREADABLE)
        await session.commit()
        log.warning("ai.connection.key_unreadable", connection_id=str(connection_id))
        return connection
    await session.rollback()
    started = _now()
    error = await _check(profile, key=key, base_url=base_url)
    connection = await _get(session, connection_id, lock=True)
    apply_result(connection, key_changed_at=changed_at, started=started, code=error)
    await session.commit()
    return connection


async def rename(session: AsyncSession, connection_id: uuid.UUID, *, name: str) -> Connection:
    connection = await _get(session, connection_id)
    connection.name = name.strip() or connection.provider
    await session.commit()
    return connection


async def delete_connection(session: AsyncSession, connection_id: uuid.UUID) -> None:
    """Задачи на нём остаются «не настроенными», журнал вызовов не теряется:
    внешние ключи ON DELETE SET NULL."""
    connection = await _get(session, connection_id, lock=True)
    await session.delete(connection)
    await session.commit()
    log.info("ai.connection.deleted", connection_id=str(connection_id))


async def _get(
    session: AsyncSession, connection_id: uuid.UUID, *, lock: bool = False
) -> Connection:
    connection = await repository.get_connection(session, connection_id, lock=lock)
    if connection is None:
        raise ConnectionNotFound
    return connection


async def set_binding(
    session: AsyncSession,
    *,
    purpose: str,
    scope: str | None,
    connection_id: uuid.UUID,
    model: str,
) -> None:
    """Через какое подключение и модель идёт задача. Без commit: зовёт модуль
    задачи в своей транзакции, вместе со своими настройками."""
    model = model.strip()
    if not model:
        raise ModelRequired
    await _get(session, connection_id)
    await repository.upsert_binding(
        session, purpose=purpose, scope=scope, connection_id=connection_id, model=model
    )
