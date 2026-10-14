"""Задачи worker в instagram. Каждая работает в переданной сессии и сама
коммитит: одна транзакция на одно событие."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity
from app.core import crypto
from app.instagram import graph, repository, service, webhook
from app.instagram.contracts import CommentRef, InboxHandlers, OutboxResult, PostbackRef
from app.instagram.models import Account, InboxEvent, OutboxTask
from app.instagram.outbox import FOLLOWING, NOT_FOLLOWING, UNKNOWN

log = structlog.get_logger("app.instagram")

MAX_ATTEMPTS = 5
# пауза перед следующей попыткой: после первого падения 10 с, после четвёртого час
RETRY_DELAYS = (
    timedelta(seconds=10),
    timedelta(minutes=1),
    timedelta(minutes=10),
    timedelta(hours=1),
)


async def process_inbox_event(session: AsyncSession, handlers: InboxHandlers) -> bool:
    """Разобрать одно входящее в своей транзакции. False: разбирать нечего."""
    event = await repository.claim_inbox_event(session)
    if event is None:
        return False
    event_id, kind = event.id, event.kind
    # id запроса вебхука в логах worker: цепочка от Meta до ответа ищется по одному id
    with structlog.contextvars.bound_contextvars(request_id=event.request_id):
        try:
            outcome, reason, handled_by = await _handle(session, event, handlers)
            _finish(event, outcome, reason, handled_by)
            await session.commit()
            log.info(
                "inbox.processed", kind=kind, outcome=outcome, reason=reason, handled_by=handled_by
            )
        except Exception as error:
            # всё сделанное для события откатывается, в том числе журнал и outbox
            await session.rollback()
            await _record_failure(session, event_id, error)
    return True


# итог разбора, причина и кто взял событие себе
Handled = tuple[str, str | None, str | None]


async def _handle(session: AsyncSession, event: InboxEvent, handlers: InboxHandlers) -> Handled:
    account = await repository.get_account_by_ig_id(session, event.ig_account_id)
    if account is None:
        # чужой аккаунт или тестовый вебхук из кабинета Meta (id 0)
        return "skipped", "unknown_account", None
    if account.status != "active":
        return "skipped", "account_inactive", None
    if event.kind == webhook.COMMENT:
        return await _handle_comment(session, event, account, handlers)
    if event.kind == webhook.POSTBACK:
        return await _handle_postback(session, event, account, handlers)
    # сообщения и прочтения пока никому не нужны
    return "done", None, None


async def _handle_postback(
    session: AsyncSession, event: InboxEvent, account: Account, handlers: InboxHandlers
) -> Handled:
    postback = _postback_ref(event, account)
    if postback is None:
        return "skipped", "bad_payload", None
    if handlers.on_postback:
        return "done", None, await handlers.on_postback(session, postback)
    return "done", None, None


def _postback_ref(event: InboxEvent, account: Account) -> PostbackRef | None:
    """Справка из payload нажатия. None, если не хватает нужного."""
    value = event.payload
    sender = _dict(value.get("sender")).get("id")
    postback = _dict(value.get("postback"))
    payload, mid = postback.get("payload"), postback.get("mid")
    if not (sender and mid and isinstance(payload, str)):
        return None
    timestamp = value.get("timestamp")
    acted_at = (
        datetime.fromtimestamp(timestamp / 1000, UTC)
        if isinstance(timestamp, int | float)
        else event.received_at
    )
    return PostbackRef(
        account_id=account.id,
        person_id=str(sender),
        payload=payload,
        mid=str(mid),
        acted_at=acted_at,
    )


async def _handle_comment(
    session: AsyncSession, event: InboxEvent, account: Account, handlers: InboxHandlers
) -> Handled:
    comment = _comment_ref(event, account)
    if comment is None:
        # повтор кривые данные не вылечит
        return "skipped", "bad_payload", None
    if comment.person_id == account.ig_user_id:
        # аккаунт сам ответил под своим постом
        return "skipped", "own_comment", None

    activity.record(
        session,
        "comment.received",
        account_id=account.id,
        person_id=comment.person_id,
        comment_id=comment.comment_id,
        data={"text": comment.text, "media_id": comment.media_id, "username": comment.username},
        occurred_at=comment.received_at,
    )
    if handlers.on_comment:
        # не взял никто: тоже разобрано, просто ни одному модулю коммент не подошёл
        return "done", None, await handlers.on_comment(session, comment)
    return "done", None, None


def _comment_ref(event: InboxEvent, account: Account) -> CommentRef | None:
    """Справка из payload коммента. None, если не хватает нужного."""
    value = event.payload
    author = _dict(value.get("from"))
    media = _dict(value.get("media"))
    comment_id, person_id, media_id = value.get("id"), author.get("id"), media.get("id")
    text = value.get("text")
    if not (comment_id and person_id and media_id and isinstance(text, str)):
        return None
    return CommentRef(
        account_id=account.id,
        comment_id=str(comment_id),
        media_id=str(media_id),
        person_id=str(person_id),
        username=author.get("username"),
        text=text,
        received_at=event.received_at,
    )


async def _record_failure(session: AsyncSession, event_id: Any, error: Exception) -> None:
    """Отдельная короткая транзакция: попытка засчитывается, хотя разбор откатился."""
    event = await session.get(InboxEvent, event_id, with_for_update=True)
    event.attempts += 1
    # только имя класса: в тексте ошибки бывают куски payload
    event.reason = type(error).__name__[:64]
    if event.attempts >= MAX_ATTEMPTS:
        _finish(event, "failed", event.reason)
        log.error("inbox.failed", attempts=event.attempts, exc_info=error)
    else:
        event.retry_at = func.now() + RETRY_DELAYS[event.attempts - 1]
        log.warning("inbox.retry", attempts=event.attempts, exc_info=error)
    await session.commit()


# --- исходящие ---

OnResult = Callable[[AsyncSession, OutboxResult], Awaitable[None]]

# лимит Meta на Private Reply в час на аккаунт
PRIVATE_REPLIES_PER_HOUR = 750
# место одного Private Reply внутри часа: 4,8 с
PRIVATE_REPLY_SLOT = timedelta(hours=1) / PRIVATE_REPLIES_PER_HOUR
SEND_TIMEOUT = 15.0
# пауза перед повтором отправки: Meta легла или притормозила нас
SEND_RETRY_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=1),
)
# коды ограничения частоты у Graph API: это временно, повторяем позже.
# Проверить вживую, какие коды отдаёт Instagram
RATE_LIMIT_CODES = {4, 17, 32, 613}


def _http() -> httpx.AsyncClient:
    # в тестах подменяется: в сеть тесты не ходят
    return httpx.AsyncClient(timeout=SEND_TIMEOUT)


async def send_outbox_task(session: AsyncSession, on_result: OnResult | None = None) -> bool:
    """Отправить одно исходящее, которому пора. False: отправлять нечего.

    Итог отправки фиксируется отдельным коммитом до того, как его узнает
    вызывающий: упади обработчик итога, письмо всё равно не уйдёт второй раз."""
    task = await repository.claim_outbox_task(session)
    if task is None:
        return False
    task_id, ref = task.id, task.ref
    with structlog.contextvars.bound_contextvars(request_id=task.request_id):
        try:
            result = await _send(session, task)
            await session.commit()
        except Exception as error:
            # ошибка нашего кода, а не Meta: откат и повтор, как у входящих
            await session.rollback()
            await _record_send_failure(session, task_id, error)
            return True
        if result is not None and ref is not None and on_result is not None:
            # итог уже закоммичен: отчёт под замком строки, подборщик его не перехватит
            task = await repository.lock_unreported_outbox_task(session, task_id)
            if task is not None:
                await _report(session, task, on_result)
    return True


# отчёт, не дошедший сразу, подбирается не раньше: основной путь успевает сам
REPORT_DELAY = timedelta(seconds=30)


async def report_outbox_result(session: AsyncSession, on_result: OnResult) -> bool:
    """Повторить отчёт об итоге, который не дошёл: упал обработчик, worker умер
    между коммитами или отправку закрыли после падений нашего кода. False: нечего."""
    task = await repository.claim_unreported_outbox_task(
        session, older_than=REPORT_DELAY, max_attempts=MAX_ATTEMPTS
    )
    if task is None:
        return False
    with structlog.contextvars.bound_contextvars(request_id=task.request_id):
        await _report(session, task, on_result)
    return True


async def _report(session: AsyncSession, task: OutboxTask, on_result: OnResult) -> None:
    """Итог тому, кто ставил письмо. Обработчик и отметка одной транзакцией:
    либо оба, либо ни одного, и второго отчёта не будет."""
    task_id, kind = task.id, task.kind
    try:
        await on_result(
            session, OutboxResult(task.ref, task.kind, task.outcome, task.reason, task.variant)
        )
        task.reported_at = func.now()
        await session.commit()
    except Exception as error:
        await session.rollback()
        await _record_report_failure(session, task_id, kind, error)


async def _record_report_failure(
    session: AsyncSession, task_id: Any, kind: str, error: Exception
) -> None:
    task = await session.get(OutboxTask, task_id, with_for_update=True)
    task.report_attempts += 1
    if task.report_attempts >= MAX_ATTEMPTS:
        # дальше не повторяем: строка остаётся без отметки, по ней видно, что не дошло
        log.error("outbox.report_dropped", kind=kind, attempts=task.report_attempts, exc_info=error)
    else:
        # пауза как у входящих: короткий сбой не съест все попытки разом
        task.report_after = func.now() + RETRY_DELAYS[task.report_attempts - 1]
        log.warning("outbox.report_retry", kind=kind, attempts=task.report_attempts, exc_info=error)
    await session.commit()


Result = tuple[str, str | None, str | None]


async def _send(session: AsyncSession, task: OutboxTask) -> Result | None:
    """Попытка отправки. Итог (outcome, reason, variant), если задача завершена;
    None, если отложена до run_at."""
    expired = task.expires_at is not None and task.expires_at <= await _now(session)
    if expired:
        return _finish_task(task, "expired", None)

    account = await repository.get_account(session, task.account_id)
    if account is None or account.status != "active" or not account.token_encrypted:
        return _finish_task(task, "failed", "account_inactive")

    if task.kind == "private_reply":
        # до конца транзакции: счёт и сама отправка не разойдутся с соседним отправителем
        await repository.lock_private_replies(session, account.id)
        count, oldest = await repository.private_replies_last_hour(session, account.id)
        if count >= PRIVATE_REPLIES_PER_HOUR:
            # не ждём, а переносим: остальные аккаунты не стоят за этим в очереди.
            # Каждому своё место через SLOT после предыдущего отложенного: иначе все
            # проснулись бы разом и пересчитывали лимит по кругу ради одного места
            last = await repository.last_planned_private_reply(session, account.id)
            first_free = oldest + timedelta(hours=1)
            task.run_at = max(first_free, last + PRIVATE_REPLY_SLOT) if last else first_free
            log.info("outbox.deferred", kind=task.kind, reason="rate_limit")
            return None

    token = crypto.decrypt(account.token_encrypted)
    try:
        async with _http() as http:
            variant = await _choose_variant(http, task, token=token)
            await _call_meta(
                http, task, token=token, ig_user_id=account.ig_user_id, variant=variant
            )
    except (graph.GraphError, httpx.HTTPError) as error:
        if isinstance(error, graph.GraphError) and error.code == service.TOKEN_INVALID:
            service.expire_account(session, account)
        return _meta_failed(task, error)
    log.info("outbox.sent", kind=task.kind, attempts=task.attempts, variant=variant)
    return _finish_task(task, "sent", None, variant)


async def _choose_variant(http: httpx.AsyncClient, task: OutboxTask, *, token: str) -> str | None:
    """Вариант сообщения с проверкой подписки; None у обычных писем. Временная ошибка
    проверки летит наверх и повторяется как ошибка отправки; окончательная (нет
    согласия человека) даёт unknown."""
    if "not_following" not in task.payload:
        return None
    try:
        follows = await graph.follows_business(
            http, token=token, person_id=task.payload["recipient_id"]
        )
    except graph.GraphError as error:
        if _temporary(error):
            raise
        log.warning("outbox.follow_unknown", reason=str(error.code or error.status))
        return UNKNOWN
    return FOLLOWING if follows else NOT_FOLLOWING


async def _call_meta(
    http: httpx.AsyncClient,
    task: OutboxTask,
    *,
    token: str,
    ig_user_id: str,
    variant: str | None,
) -> None:
    payload = task.payload
    # unknown: тот вариант, что вызывающий выбрал на случай непроверенной подписки
    chosen = payload.get("if_unknown") if variant == UNKNOWN else variant
    message = payload["not_following"] if chosen == NOT_FOLLOWING else payload
    if task.kind == "comment_reply":
        await graph.reply_to_comment(
            http, token=token, comment_id=payload["comment_id"], text=payload["text"]
        )
        return
    recipient = (
        {"comment_id": payload["comment_id"]}
        if task.kind == "private_reply"
        else {"id": payload["recipient_id"]}
    )
    await graph.send_message(
        http,
        token=token,
        ig_user_id=ig_user_id,
        recipient=recipient,
        text=message["text"],
        button=message.get("button"),
    )


def _temporary(error: graph.GraphError) -> bool:
    return error.status >= 500 or error.status == 429 or error.code in RATE_LIMIT_CODES


def _meta_failed(task: OutboxTask, error: Exception) -> Result | None:
    """Meta ответила ошибкой или не ответила. Временное повторяем, окончательное нет."""
    if isinstance(error, graph.GraphError):
        reason = str(error.code if error.code is not None else error.status)
        temporary = _temporary(error)
    else:
        # сеть: таймаут, обрыв
        reason, temporary = type(error).__name__, True
    task.attempts += 1
    task.reason = reason[:64]
    if temporary and task.attempts < MAX_ATTEMPTS:
        task.run_at = func.now() + SEND_RETRY_DELAYS[task.attempts - 1]
        log.warning("outbox.retry", kind=task.kind, attempts=task.attempts, reason=reason)
        return None
    log.warning("outbox.failed", kind=task.kind, attempts=task.attempts, reason=reason)
    return _finish_task(task, "failed", reason)


async def _record_send_failure(session: AsyncSession, task_id: Any, error: Exception) -> None:
    task = await session.get(OutboxTask, task_id, with_for_update=True)
    task.attempts += 1
    task.reason = type(error).__name__[:64]
    if task.attempts >= MAX_ATTEMPTS:
        _finish_task(task, "failed", task.reason)
        log.error("outbox.failed", attempts=task.attempts, exc_info=error)
    else:
        task.run_at = func.now() + SEND_RETRY_DELAYS[task.attempts - 1]
        log.warning("outbox.retry", attempts=task.attempts, exc_info=error)
    await session.commit()


def _finish_task(
    task: OutboxTask, outcome: str, reason: str | None, variant: str | None = None
) -> Result:
    task.outcome = outcome
    task.reason = reason
    task.variant = variant
    task.finished_at = func.now()
    return outcome, reason, variant


async def _now(session: AsyncSession):
    # время базы, а не процесса: сроки задач тоже считала база
    return await session.scalar(func.now().select())


# --- токены ---

# токен живёт 60 дней; обновляем, когда осталось меньше 50: Meta требует старше
# суток, а при её сбоях у нас недели на повторы, а не часы
REFRESH_WHEN_LEFT = timedelta(days=50)


async def refresh_due_tokens(session: AsyncSession) -> int:
    """Обновить токены всех аккаунтов, которым пора. Каждый в своей транзакции:
    сбой у одного не мешает остальным, неудачный попробуем в следующий запуск."""
    refreshed = 0
    for account_id in await repository.accounts_due_refresh(session, left=REFRESH_WHEN_LEFT):
        with structlog.contextvars.bound_contextvars(account_id=str(account_id)):
            try:
                refreshed += await _refresh_one(session, account_id)
            except (graph.GraphError, httpx.HTTPError) as error:
                await session.rollback()
                reason = (
                    str(error.code or error.status)
                    if isinstance(error, graph.GraphError)
                    else type(error).__name__
                )
                log.warning("account.token_refresh_failed", reason=reason)
    return refreshed


async def _refresh_one(session: AsyncSession, account_id: Any) -> int:
    account = await repository.lock_account_due_refresh(session, account_id, left=REFRESH_WHEN_LEFT)
    if account is None:
        await session.rollback()
        return 0
    try:
        async with _http() as http:
            fresh = await graph.refresh_token(http, token=crypto.decrypt(account.token_encrypted))
    except graph.GraphError as error:
        if error.code != service.TOKEN_INVALID:
            raise
        service.expire_account(session, account)
        await session.commit()
        return 0
    account.token_encrypted = crypto.encrypt(fresh.access_token)
    expires_at = await _now(session) + timedelta(seconds=fresh.expires_in)
    account.token_expires_at = expires_at
    await session.commit()
    log.info("account.token_refreshed", expires_at=expires_at.isoformat())
    return 1


def _finish(
    event: InboxEvent, outcome: str, reason: str | None, handled_by: str | None = None
) -> None:
    event.processed_at = func.now()
    event.outcome = outcome
    event.reason = reason
    event.handled_by = handled_by
    event.retry_at = None


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
