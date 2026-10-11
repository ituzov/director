"""Задачи worker в instagram. Каждая работает в переданной сессии и сама
коммитит: одна транзакция на одно событие."""

from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity
from app.instagram import repository, webhook
from app.instagram.contracts import CommentRef, InboxHandlers
from app.instagram.models import Account, InboxEvent

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
            outcome, reason = await _handle(session, event, handlers)
            _finish(event, outcome, reason)
            await session.commit()
            log.info("inbox.processed", kind=kind, outcome=outcome, reason=reason)
        except Exception as error:
            # всё сделанное для события откатывается, в том числе журнал и outbox
            await session.rollback()
            await _record_failure(session, event_id, error)
    return True


async def _handle(
    session: AsyncSession, event: InboxEvent, handlers: InboxHandlers
) -> tuple[str, str | None]:
    account = await repository.get_account_by_ig_id(session, event.ig_account_id)
    if account is None:
        # чужой аккаунт или тестовый вебхук из кабинета Meta (id 0)
        return "skipped", "unknown_account"
    if account.status != "active":
        return "skipped", "account_inactive"
    if event.kind != webhook.COMMENT:
        # сообщения, кнопки и прочтения пока никому не нужны
        return "done", None

    comment = _comment_ref(event, account)
    if comment is None:
        # повтор кривые данные не вылечит
        return "skipped", "bad_payload"
    if comment.person_id == account.ig_user_id:
        # аккаунт сам ответил под своим постом
        return "skipped", "own_comment"

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
        await handlers.on_comment(session, comment)
    return "done", None


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


def _finish(event: InboxEvent, outcome: str, reason: str | None) -> None:
    event.processed_at = func.now()
    event.outcome = outcome
    event.reason = reason
    event.retry_at = None


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
