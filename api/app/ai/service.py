"""Подключения к провайдерам моделей: сохранить ключ с проверкой, заменить,
переименовать, проверить ещё раз, удалить.

Сеть идёт до записи в базу и вне транзакции: пока провайдер думает (до
CHECK_TIMEOUT), ни одна строка не заперта. Ключ в логи не попадает, даже
последними символами.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import NamedTuple

import httpx2
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import providers, repository
from app.ai.exceptions import (
    BaseUrlNotAllowed,
    BaseUrlRequired,
    ConnectionNotFound,
    KeyInvalidChars,
    KeyRejected,
    KeyTooShort,
    ModelRequired,
    UnknownProvider,
)
from app.ai.models import Binding, Connection
from app.ai.providers.base import KEY_REJECTED, NO_FUNDS, ModelInfo, Provider, ProviderError
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


class Models(NamedTuple):
    """Модели подключения по id и код ошибки, если провайдер не ответил."""

    models: list[ModelInfo]
    error: str | None


class Checked(NamedTuple):
    """Подключение и итог проверки ключа (None: ключ работает). Итог отдельно от
    карточки: разовый сбой карточку не меняет, и без него «Проверить ещё раз» с
    таймаутом выглядело бы как кнопка, которая ничего не делает."""

    connection: Connection
    error: str | None


def _http() -> httpx2.AsyncClient:
    # один клиент на проверку; тесты подменяют эту функцию
    return httpx2.AsyncClient(timeout=CHECK_TIMEOUT)


def _now() -> datetime:
    return datetime.now(UTC)


async def _before_network(session: AsyncSession) -> None:
    """Закрыть транзакцию перед сетью: проверка ключа идёт до 15 с, а открытая
    транзакция держит соединение и замки чтения. Транзакцию могла открыть и ручка
    (текущий пользователь). commit, а не rollback: в ней только читали, а
    rollback пометил бы устаревшими все объекты сессии, и ручка, обратившись к
    пользователю, упала бы на неявном перечитывании."""
    await session.commit()


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
    # настоящие ключи из латиницы, цифр и знаков; иное уронило бы сборку заголовка
    if not all("!" <= c <= "~" for c in key):
        raise KeyInvalidChars
    return key


async def _call[T](
    provider: Provider, request: Callable[[httpx2.AsyncClient], Awaitable[T]]
) -> tuple[T | None, str | None]:
    """Запрос к провайдеру: проверка ключа или список моделей. Итог и наш код
    ошибки, None вместо кода: провайдер ответил."""
    try:
        async with _http() as http:
            return await request(http), None
    except ProviderError as error:
        log.warning(
            "ai.connection.check_failed",
            provider=provider.kind,
            code=error.code,
            http_status=error.http_status,
        )
        return None, error.code


async def _check(provider: Provider, *, key: str, base_url: str | None) -> str | None:
    """Пробный запрос. None: ключ работает. Иначе наш код ошибки."""
    _, error = await _call(
        provider, lambda http: provider.check_key(http, key=key, base_url=base_url)
    )
    return error


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


async def bindings_by_connection(
    session: AsyncSession, connection_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Binding]]:
    """Какие задачи идут через каждое подключение: для карточек."""
    found: dict[uuid.UUID, list[Binding]] = {i: [] for i in connection_ids}
    for binding in await repository.list_bindings(session, connection_ids):
        found[binding.connection_id].append(binding)
    return found


async def create_connection(
    session: AsyncSession,
    *,
    provider: str,
    name: str,
    key: str,
    base_url: str | None,
    created_by: uuid.UUID,
) -> Checked:
    """Сохранить ключ. Ключ, который провайдер не принял, не сохраняем: он не
    заработает, а владелец скорее скопировал его не целиком. Остальное сохраняем:
    нет денег чинится пополнением, сбой пройдёт сам."""
    profile = _provider(provider)
    base_url = _base_url(profile, base_url)
    key = _key(key)
    await _before_network(session)
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
    return Checked(connection, error)


async def replace_key(session: AsyncSession, connection_id: uuid.UUID, *, key: str) -> Checked:
    """Новый ключ вместо старого, с той же проверкой. key_changed_at сдвигается:
    401 от старого ключа, долетевший после замены, новый не окрасит."""
    connection = await _get(session, connection_id)
    profile = _provider(connection.provider)
    base_url = connection.base_url
    key = _key(key)
    # сеть вне транзакции: прочитанное выше не держим, после проверки перечитаем
    await _before_network(session)
    started = _now()
    error = await _check(profile, key=key, base_url=base_url)
    if error == KEY_REJECTED:
        raise KeyRejected
    # подключение могли удалить, пока шла проверка: тогда не создаём его заново
    connection = await _get(session, connection_id, lock=True)
    _new_key(connection, key)
    # 404 «модели нет» получал старый ключ: на другом аккаунте провайдера модель есть
    await repository.clear_model_missing(session, connection_id)
    apply_result(connection, key_changed_at=connection.key_changed_at, started=started, code=error)
    await session.commit()
    log.info(
        "ai.connection.key_replaced",
        connection_id=str(connection_id),
        checked=connection.checked_at is not None,
        error_code=connection.error_code,
    )
    return Checked(connection, error)


async def recheck(session: AsyncSession, connection_id: uuid.UUID) -> Checked:
    """«Проверить ещё раз»: пополнил баланс или ключ поменяли в панели провайдера.
    Ключ не принят здесь пишется на карточку, а не бросается: ключ уже сохранён."""
    connection, _, error = await _probe(
        session, connection_id, lambda p, http, key, url: p.check_key(http, key=key, base_url=url)
    )
    log.info(
        "ai.connection.rechecked",
        connection_id=str(connection_id),
        checked=connection.checked_at is not None,
        error_code=connection.error_code,
    )
    return Checked(connection, error)


async def list_models(session: AsyncSession, connection_id: uuid.UUID) -> Models:
    """Модели подключения для выбора в задаче. Это тот же запрос, что проверка
    ключа, поэтому итог ложится на карточку: иначе список сказал бы «ключ не
    принят», а карточка осталась бы зелёной. Провайдер не ответил: пустой список и
    код, а не исключение, окно выбора предложит повторить."""
    _, models, error = await _probe(
        session, connection_id, lambda p, http, key, url: p.models(http, key=key, base_url=url)
    )
    return Models(sorted(models or [], key=lambda m: m.id), error)


async def _probe[T](
    session: AsyncSession,
    connection_id: uuid.UUID,
    request: Callable[[Provider, httpx2.AsyncClient, str, str | None], Awaitable[T]],
) -> tuple[Connection, T | None, str | None]:
    """Запрос к провайдеру по сохранённому ключу и итог на карточку. Сеть вне
    транзакции, итог под замком строки: замена ключа, успевшая за время запроса,
    итог про старый ключ не получит (сверка отпечатка в apply_result)."""
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
        return connection, None, KEY_UNREADABLE
    await _before_network(session)
    started = _now()
    result, error = await _call(profile, lambda http: request(profile, http, key, base_url))
    connection = await _get(session, connection_id, lock=True)
    apply_result(connection, key_changed_at=changed_at, started=started, code=error)
    await session.commit()
    return connection, result, error


async def rename(session: AsyncSession, connection_id: uuid.UUID, *, name: str) -> Connection:
    # под замком: удаление между чтением и записью дало бы StaleDataError и 500
    connection = await _get(session, connection_id, lock=True)
    connection.name = name.strip() or connection.provider
    await session.commit()
    log.info("ai.connection.renamed", connection_id=str(connection_id))
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
    # под замком: удаление между проверкой и записью дало бы IntegrityError по
    # внешнему ключу вместо ConnectionNotFound
    await _get(session, connection_id, lock=True)
    await repository.upsert_binding(
        session, purpose=purpose, scope=scope, connection_id=connection_id, model=model
    )
