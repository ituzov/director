"""Сценарии instagram. Одна функция это одна операция и один commit."""

import asyncio
import hashlib
import hmac
import json
import secrets
import ssl
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity
from app.config import settings
from app.core import crypto, signing
from app.instagram import graph, repository, webhook
from app.instagram.contracts import AccountRef
from app.instagram.exceptions import (
    AccountNotFound,
    AccountUnavailable,
    AppSecretRequired,
    InvalidOAuthState,
    MetaAppRequired,
    MetaUnavailable,
    OAuthFailed,
    PublicUrlRequired,
)
from app.instagram.models import Account, InboxEvent, MetaApp

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


async def list_accounts(session: AsyncSession) -> list[Account]:
    return await repository.list_accounts(session)


# токен недействителен: истёк, отозван, сменили пароль. Только новый вход
TOKEN_INVALID = 190


def expire_account(session: AsyncSession, account: Account) -> None:
    """Токен больше не годен: бот у аккаунта молчит, пока владелец не войдёт заново.
    Сам токен стираем: хранить бесполезный секрет незачем. Без commit."""
    account.status = "token_expired"
    account.token_encrypted = None
    activity.record(session, "account.token_expired", account_id=account.id)
    log.warning("account.token_expired", account_id=str(account.id))


async def list_media(
    session: AsyncSession, account_id: uuid.UUID, *, after: str | None, limit: int
) -> graph.MediaPage:
    """Посты аккаунта страницами, прямо из Meta: ничего не храним."""
    account, token = await _media_access(session, account_id)
    try:
        async with _http() as http:
            return await graph.list_media(http, token=token, after=after, limit=limit)
    except (graph.GraphError, httpx.HTTPError) as error:
        await _media_failed(session, account, error)


async def get_media(
    session: AsyncSession, account_id: uuid.UUID, media_ids: list[str]
) -> dict[str, dict | None]:
    """Посты по id, для выбранных в автоответе. None у поста, которого Meta не знает:
    его удалили или убрали в архив, а автоответ на нём ещё висит."""
    account, token = await _media_access(session, account_id)
    async with _http() as http:
        # параллельно: постов у автоответа немного, а по одному это секунды ожидания.
        # Ошибки собираем, а не бросаем сразу, чтобы не оставлять запросы висеть
        results = await asyncio.gather(
            *(graph.get_media(http, token=token, media_id=i) for i in media_ids),
            return_exceptions=True,
        )
    errors = [r for r in results if isinstance(r, BaseException)]
    if errors:
        # токен истёк: это важнее, чем «Meta не ответила» у соседнего запроса
        expired = [e for e in errors if isinstance(e, graph.GraphError) and e.code == TOKEN_INVALID]
        failure = (expired or errors)[0]
        if not isinstance(failure, (graph.GraphError, httpx.HTTPError)):
            raise failure
        await _media_failed(session, account, failure)
    return {
        i: r for i, r in zip(media_ids, results, strict=True) if not isinstance(r, BaseException)
    }


async def _media_access(session: AsyncSession, account_id: uuid.UUID) -> tuple[Account, str]:
    """Аккаунт и его токен для чтения постов, или AccountUnavailable."""
    account = await repository.get_account(session, account_id)
    if account is None or account.status != "active" or not account.token_encrypted:
        raise AccountUnavailable
    return account, crypto.decrypt(account.token_encrypted)


async def _media_failed(
    session: AsyncSession, account: Account, error: graph.GraphError | httpx.HTTPError
) -> NoReturn:
    """Ошибка Meta при чтении постов в одну из двух, понятных форме: токен истёк
    (AccountUnavailable) или Meta не ответила (MetaUnavailable)."""
    if isinstance(error, graph.GraphError):
        if error.code == TOKEN_INVALID:
            expire_account(session, account)
            await session.commit()
            raise AccountUnavailable from error
        reason = str(error.code or error.status)
    else:
        reason = type(error).__name__
    log.warning("media.list_failed", reason=reason)
    raise MetaUnavailable from error


async def count_undelivered(
    session: AsyncSession, account_id: uuid.UUID, *, since: datetime, ref_prefix: str
) -> int:
    """Для соседей: сколько их отправок не дошло. ref_prefix это метка соседа
    («autoreplies:»), по ней отделяем свои задачи от чужих."""
    return await repository.count_undelivered(
        session, account_id, since=since, ref_prefix=ref_prefix
    )


async def get_account(session: AsyncSession, account_id: uuid.UUID) -> AccountRef | None:
    """Аккаунт для соседей: справка без токена, None если такого нет."""
    account = await repository.get_account(session, account_id)
    if account is None:
        return None
    return AccountRef(
        id=account.id,
        ig_user_id=account.ig_user_id,
        username=account.username,
        status=account.status,
    )


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


def _signature_ok(body: bytes, header: str, secret: str) -> bool:
    # HMAC от сырых байтов тела: любое переформатирование JSON ломает подпись
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # в байтах: строка заголовка может быть не ASCII, и тогда compare_digest падает
    return hmac.compare_digest(expected.encode(), header.encode("latin-1"))


async def receive_webhook(session: AsyncSession, *, body: bytes, signature: str | None) -> bool:
    """Принять вебхук Meta во входящие. False, если он не от Meta (подпись не наша).
    Разбирает worker: здесь только проверка, отбор и запись, чтобы ответить быстро."""
    meta_app = await repository.get_meta_app(session)
    if meta_app is None:
        reason = "no_app"
    elif not signature:
        reason = "no_signature"
    elif not _signature_ok(body, signature, crypto.decrypt(meta_app.app_secret_encrypted)):
        reason = "bad_signature"
    else:
        try:
            payload = json.loads(body)
        except ValueError:
            # подпись наша, а тело не JSON: повтор не поможет, принимаем пустым
            log.warning("webhook.bad_json")
            payload = None
        parsed = webhook.parse_webhook(payload)
        # id запроса едет с событием: worker поднимет его в свои логи
        request_id = structlog.contextvars.get_contextvars().get("request_id")
        stored = await repository.add_inbox_events(
            session,
            [
                {
                    "ig_account_id": item.ig_account_id,
                    "kind": item.kind,
                    "dedup_key": item.dedup_key,
                    "payload": item.payload,
                    "request_id": request_id,
                }
                for item in parsed.items
            ],
        )
        # вся пачка одним commit: легла целиком или никак, и тогда Meta повторит
        await session.commit()
        log.info(
            "webhook.received",
            events=len(parsed.items),
            stored=stored,
            skipped=sorted(set(parsed.skipped)),
        )
        return True
    log.warning("webhook.rejected", reason=reason)
    return False


# что просим у человека на экране Instagram
SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_comments",
    "instagram_business_manage_messages",
]
# на что подписываем аккаунт: остальное включим вместе с фичами
FIELDS = ["comments", "messages", "messaging_postbacks", "messaging_seen"]
# пропуск входа живёт 10 минут: дольше человек на экране Instagram не сидит
STATE_PURPOSE = "instagram-oauth"
STATE_MAX_AGE = 600
AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"


async def oauth_url(session: AsyncSession, *, user_id: uuid.UUID) -> str:
    """Адрес экрана Instagram, куда уводим человека подключать аккаунт."""
    meta_app = await repository.get_meta_app(session)
    if meta_app is None:
        raise MetaAppRequired
    redirect_uri = public_url(OAUTH_CALLBACK_PATH)
    if redirect_uri is None:
        raise PublicUrlRequired
    # соль: два входа подряд дают разные пропуски
    state = signing.sign({"u": str(user_id), "n": secrets.token_hex(8)}, purpose=STATE_PURPOSE)
    query = urlencode(
        {
            "client_id": meta_app.app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(SCOPES),
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def connect_account(
    session: AsyncSession, *, user_id: uuid.UUID, code: str, state: str
) -> Account:
    """Возврат с экрана Instagram: код в долгий токен, подписка на вебхуки, аккаунт в базу."""
    try:
        data = signing.unsign(state, purpose=STATE_PURPOSE, max_age=STATE_MAX_AGE)
    except signing.SignatureError:
        raise InvalidOAuthState from None
    # пропуск выдан другому пользователю: кто-то подсунул чужую ссылку возврата
    if data.get("u") != str(user_id):
        raise InvalidOAuthState

    meta_app = await repository.get_meta_app(session)
    redirect_uri = public_url(OAUTH_CALLBACK_PATH)
    if meta_app is None or redirect_uri is None:
        raise InvalidOAuthState
    app_secret = crypto.decrypt(meta_app.app_secret_encrypted)

    step = "exchange_code"
    try:
        async with _http() as http:
            short = await graph.exchange_code(
                http,
                app_id=meta_app.app_id,
                app_secret=app_secret,
                redirect_uri=redirect_uri,
                code=code,
            )
            step = "long_lived_token"
            long = await graph.long_lived_token(
                http, app_secret=app_secret, short_token=short.access_token
            )
            step = "get_me"
            me = await graph.get_me(http, token=long.access_token)
            # подписка до записи: упала, значит аккаунта нет, и человек просто повторит.
            # Наоборот остался бы «подключённый» аккаунт, на который не приходят события
            step = "subscribe"
            await graph.subscribe(http, token=long.access_token, fields=FIELDS)
    except (graph.GraphError, httpx.HTTPError) as exc:
        # текст ошибки Meta не пишем: только шаг, код и тип
        log.warning(
            "account.connect_failed",
            step=step,
            status=getattr(exc, "status", None),
            code=getattr(exc, "code", None),
            type=getattr(exc, "type", None) or type(exc).__name__,
        )
        raise OAuthFailed from None

    account = await repository.upsert_account(
        session,
        ig_user_id=me.user_id,
        username=me.username,
        token_encrypted=crypto.encrypt(long.access_token),
        token_expires_at=datetime.now(UTC) + timedelta(seconds=long.expires_in),
        connected_by=user_id,
    )
    await session.commit()
    # совпадает ли id из /me с entry[].id вебхуков, проверим вживую: оба id в лог
    log.info(
        "account.connected",
        ig_user_id=me.user_id,
        oauth_user_id=short.user_id,
        username=me.username,
        permissions=short.permissions,
    )
    return account


# --- лента входящих -----------------------------------------------------------------

# прочтения ничего не говорят о человеке и забили бы ленту
INBOX_KINDS = (webhook.COMMENT, webhook.POSTBACK, webhook.MESSAGE)


@dataclass(frozen=True, slots=True)
class InboxItem:
    """Входящее для ленты: то, что нужно человеку, без сырого вебхука Meta."""

    id: uuid.UUID
    received_at: datetime
    kind: str
    person_id: str | None
    username: str | None
    # текст коммента или сообщения, подпись нажатой кнопки
    text: str | None
    # вид вложения сообщения без текста: ig_reel, image, share
    attachment: str | None
    media_id: str | None
    # id коммента у Meta: по нему соседи рассказывают, что было дальше
    comment_id: str | None
    # None: worker ещё не разобрал
    outcome: str | None
    reason: str | None
    handled_by: str | None
    handled_ref: str | None


@dataclass(frozen=True, slots=True)
class InboxPage:
    items: list[InboxItem]
    # закладка следующей страницы: id последнего события; None, если дальше пусто
    next: uuid.UUID | None


async def list_inbox(
    session: AsyncSession, account_id: uuid.UUID, *, before: uuid.UUID | None, limit: int
) -> InboxPage:
    """Что пришло от Meta на аккаунт и что с этим стало. Отключённый аккаунт тоже:
    история остаётся."""
    account = await repository.get_account(session, account_id)
    if account is None:
        raise AccountNotFound
    events = await repository.inbox_page(
        session, account.ig_user_id, INBOX_KINDS, before=before, limit=limit
    )
    more = len(events) > limit
    events = events[:limit]
    items = [_inbox_item(e) for e in events]
    # ник для нажатий и сообщений: Meta присылает в них только id
    missing = sorted({i.person_id for i in items if i.person_id and not i.username})
    names = await repository.usernames_from_comments(session, account.ig_user_id, missing)
    items = [
        _with_username(i, names[i.person_id]) if i.person_id in names and not i.username else i
        for i in items
    ]
    return InboxPage(items=items, next=events[-1].id if more else None)


def _inbox_item(event: InboxEvent) -> InboxItem:
    p = _obj(event.payload)
    person = username = text = attachment = media_id = comment_id = None
    if event.kind == webhook.COMMENT:
        author = _obj(p.get("from"))
        person, username = _str(author.get("id")), _str(author.get("username"))
        text, media_id = _str(p.get("text")), _str(_obj(p.get("media")).get("id"))
        comment_id = _str(p.get("id"))
    else:
        person = _str(_obj(p.get("sender")).get("id"))
        if event.kind == webhook.POSTBACK:
            text = _str(_obj(p.get("postback")).get("title"))
        else:
            message = _obj(p.get("message"))
            text = _str(message.get("text"))
            files = message.get("attachments")
            if not text and isinstance(files, list) and files:
                attachment = _str(_obj(files[0]).get("type"))
    return InboxItem(
        id=event.id,
        received_at=event.received_at,
        kind=event.kind,
        person_id=person,
        username=username,
        text=text,
        attachment=attachment,
        media_id=media_id,
        comment_id=comment_id,
        outcome=event.outcome,
        reason=event.reason,
        handled_by=event.handled_by,
        handled_ref=event.handled_ref,
    )


def _with_username(item: InboxItem, username: str) -> InboxItem:
    return replace(item, username=username)


def _obj(value: Any) -> dict:
    # вебхук пишет Meta: любое поле может оказаться не тем типом
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    # bool наследник int: True не должен стать «True»
    if isinstance(value, bool) or not isinstance(value, str | int) or value == "":
        return None
    return str(value)
