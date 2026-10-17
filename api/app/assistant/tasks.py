"""Работа ассистента в worker: коммент в очередь, ответ нейросети, итог отправки.

Разбор входящих только ставит коммент в очередь, в транзакции события и без сети:
ответ модели идёт секунды, и под ним встали бы все автоответы и кнопки.
"""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import instagram
from app.assistant import repository

log = structlog.get_logger("app.assistant")


@dataclass(frozen=True, slots=True)
class Taken:
    """Коммент взял ассистент: какой. Отвечать или промолчать, он решит позже."""

    assistant_id: uuid.UUID


async def handle_comment(session: AsyncSession, comment: instagram.CommentRef) -> Taken | None:
    """Коммент, который не взял ни один автоответ. Отвечает частный ассистент поста,
    без него общий. На паузе держит своё место: тогда молчат все. None: не наш."""
    if comment.parent_id is not None:
        # ответ на коммент, чаще всего под нашим же ответом: каждый такой давал бы
        # ещё одно сообщение в директ. Продолжение разговора потом
        return None
    assistant = await repository.post_holder(session, comment.media_id)
    if assistant is None:
        assistant = await repository.live_general(session, comment.account_id, None)
    if assistant is None or not assistant.enabled:
        return None
    reply_id = await repository.add_reply(
        session,
        assistant_id=assistant.id,
        account_id=comment.account_id,
        comment_id=comment.comment_id,
        media_id=comment.media_id,
        person_id=comment.person_id,
        comment_text=comment.text,
        commented_at=comment.received_at,
    )
    if reply_id is not None:
        log.info("assistant.queued", assistant_id=str(assistant.id), reply_id=str(reply_id))
    return Taken(assistant.id)
