"""Постановка исходящих в очередь. Зовут соседи в своей транзакции: задача ляжет
вместе с их решением или не ляжет вовсе. Отправляет worker (tasks.send_outbox_task)."""

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.instagram.contracts import Button
from app.instagram.models import OutboxTask

# Private Reply Meta принимает 7 дней от коммента
PRIVATE_REPLY_WINDOW = timedelta(days=7)
# обычное сообщение: 24 часа от последнего действия человека
MESSAGE_WINDOW = timedelta(hours=24)

# варианты сообщения с проверкой подписки
FOLLOWING = "following"
NOT_FOLLOWING = "not_following"
UNKNOWN = "unknown"


async def enqueue_private_reply(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    comment_id: str,
    commented_at: datetime,
    text: str,
    button: Button | None = None,
    ref: str | None = None,
) -> bool:
    """Ответ в директ на коммент. Один на коммент: False, если уже стоит."""
    return await _enqueue(
        session,
        account_id=account_id,
        kind="private_reply",
        payload={"comment_id": comment_id, "text": text, **_button(button)},
        dedup_key=f"private_reply:{comment_id}",
        expires_at=commented_at + PRIVATE_REPLY_WINDOW,
        ref=ref,
    )


async def enqueue_message(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    recipient_id: str,
    acted_at: datetime,
    text: str,
    dedup_key: str,
    button: Button | None = None,
    ref: str | None = None,
    if_not_following: tuple[str, Button | None] | None = None,
    if_unknown: str = FOLLOWING,
) -> bool:
    """Сообщение в директ. Можно только 24 часа после действия человека (acted_at).
    dedup_key задаёт вызывающий: например, одно сообщение на нажатие кнопки.

    if_not_following: (текст, кнопка) для неподписанных. Тогда перед отправкой
    проверяется подписка, а text и button уходят подписанным. if_unknown: какой
    вариант слать, если Meta не дала проверить (following или not_following)."""
    payload: dict = {"recipient_id": recipient_id, "text": text, **_button(button)}
    if if_not_following is not None:
        other_text, other_button = if_not_following
        payload["not_following"] = {"text": other_text, **_button(other_button)}
        payload["if_unknown"] = if_unknown
    return await _enqueue(
        session,
        account_id=account_id,
        kind="message",
        payload=payload,
        dedup_key=f"message:{dedup_key}",
        expires_at=acted_at + MESSAGE_WINDOW,
        ref=ref,
    )


async def enqueue_comment_reply(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    comment_id: str,
    text: str,
    ref: str | None = None,
) -> bool:
    """Публичный ответ под комментом. Один на коммент."""
    return await _enqueue(
        session,
        account_id=account_id,
        kind="comment_reply",
        payload={"comment_id": comment_id, "text": text},
        dedup_key=f"comment_reply:{comment_id}",
        expires_at=None,
        ref=ref,
    )


async def _enqueue(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    kind: str,
    payload: dict,
    dedup_key: str,
    expires_at: datetime | None,
    ref: str | None,
) -> bool:
    # id запроса вебхука, пока мы внутри его разбора: логи отправки склеятся с ним
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    task_id = await session.scalar(
        insert(OutboxTask)
        .values(
            account_id=account_id,
            kind=kind,
            payload=payload,
            dedup_key=dedup_key,
            expires_at=expires_at,
            ref=ref,
            request_id=request_id,
        )
        .on_conflict_do_nothing(index_elements=[OutboxTask.dedup_key])
        .returning(OutboxTask.id)
    )
    return task_id is not None


def _button(button: Button | None) -> dict:
    return {"button": {"title": button.title, "payload": button.payload}} if button else {}
