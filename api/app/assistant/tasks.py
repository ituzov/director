"""Работа ассистента в worker: коммент в очередь, ответ нейросети, итог отправки.

Разбор входящих только ставит коммент в очередь, в транзакции события и без сети:
ответ модели идёт секунды, и под ним встали бы все автоответы и кнопки.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity, ai, instagram
from app.assistant import prompt, repository
from app.assistant.models import Reply
from app.assistant.service import ANSWER, day_start
from app.db import SessionLocal

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


# на коммент сутками позже отвечать странно: такой остаётся без ответа (expired)
TOO_OLD = timedelta(hours=24)
# дольше думать нейросеть не может (ai.CALL_TIMEOUT 120 с и переспросы): строка
# в thinking старше этого брошена упавшим worker
STUCK = timedelta(minutes=5)
# разовые сбои нейросети: повтор через минуту, потом через пять, потом failed
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5))
# всего попыток на коммент, вместе с брошенными упавшим worker
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
# сбой пройдёт сам; остальные коды (ключ, деньги, не настроено) без повтора
TRANSIENT = frozenset({"timeout", "server", "rate_limited", "bad_response", "cancelled"})

# метка письма в очереди исходящих: по ней итог отправки вернётся сюда
REF = "assistant:{reply_id}:{part}"
DIRECT, COMMENT = "direct", "comment"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _Job:
    """Что прочитали при взятии: дальше до ответа нейросети в базу не ходим."""

    reply_id: uuid.UUID
    assistant_id: uuid.UUID
    taken_at: datetime
    text: str
    brief: prompt.Brief


async def answer_once(make_session=SessionLocal) -> bool:
    """Ответить на один коммент из очереди. False: отвечать не на что.

    Три шага: взять (короткая транзакция), спросить нейросеть (вне транзакции,
    ai.run берёт свои сессии), записать решение (короткая транзакция)."""
    async with make_session() as session:
        taken = await _take(session)
    if taken is None:
        return False
    if not isinstance(taken, _Job):
        # решилось без нейросети: пауза, предел, опоздал, человек занят
        return True
    try:
        result = await ai.run(
            purpose=ANSWER,
            scope=str(taken.assistant_id),
            agent=prompt.agent(taken.brief),
            prompt=prompt.comment_prompt(taken.text),
            make_session=make_session,
        )
    except ai.AiCallFailed as error:
        async with make_session() as session:
            await _failed(session, taken, error.code)
        return True
    async with make_session() as session:
        await _record(session, taken, result.output)
    return True


async def _take(session: AsyncSession) -> _Job | bool | None:
    """Взять коммент. _Job: спросить нейросеть; True: решилось без неё; None:
    очередь пуста."""
    now = _now()
    released = await repository.release_stuck(session, now - STUCK)
    if released:
        log.warning("assistant.released_stuck", count=released)
    reply = await repository.claim_reply(session, now)
    if reply is None:
        await session.commit()
        return None
    # комменты одного человека по очереди: соседний цикл мог взять другой его
    # коммент секундой раньше, под замком на человека видно точно
    await repository.lock_person(session, reply.account_id, reply.person_id)
    if await repository.person_busy(session, reply):
        reply.run_at = now + timedelta(seconds=5)
        await session.commit()
        return True
    assistant = await repository.lock_assistant(session, reply.assistant_id)
    if assistant is None or assistant.archived_at is not None or not assistant.enabled:
        await _finish(session, reply, "paused")
        return True
    if reply.commented_at < now - TOO_OLD:
        await _finish(session, reply, "expired")
        return True
    if reply.attempts >= MAX_ATTEMPTS:
        # брошен упавшим worker столько раз, что дальше пробовать незачем
        reply.error_code = "stuck"
        await _finish(session, reply, "failed")
        return True
    # предел под замком ассистента: два цикла не прочитают 201-й из 200
    if await repository.taken_since(session, assistant.id, day_start(now)) >= assistant.daily_limit:
        await _finish(session, reply, "limit")
        return True
    reply.stage, reply.taken_at = "thinking", now
    reply.attempts += 1
    job = _Job(
        reply.id,
        assistant.id,
        now,
        reply.comment_text,
        prompt.Brief(assistant.mode, assistant.instruction, assistant.knowledge),
    )
    await session.commit()
    return job


async def _record(session: AsyncSession, job: _Job, decision: prompt.Decision) -> None:
    """Решение нейросети: ответ в очередь исходящих или тишина, итог в журнал."""
    reply = await _still_ours(session, job)
    if reply is None:
        return
    assistant = await repository.lock_assistant(session, job.assistant_id)
    # поставили на паузу, пока нейросеть думала: ответ не уходит
    if assistant is None or assistant.archived_at is not None or not assistant.enabled:
        await _finish(session, reply, "paused")
        return
    reply.source = decision.source
    if decision.decision != "answer":
        await _finish(session, reply, "unsure" if decision.decision == "unsure" else "not_mine")
        return
    reply.comment_reply, reply.direct_reply = decision.comment, decision.direct
    if assistant.mode == "comment":
        queued = await instagram.enqueue_comment_reply(
            session,
            account_id=reply.account_id,
            comment_id=reply.comment_id,
            text=decision.comment or "",
            ref=REF.format(reply_id=reply.id, part=COMMENT),
        )
    else:
        # combo тоже начинает с директа: коммент «написали в директ» встанет,
        # только когда директ ушёл, иначе он пообещает то, чего нет
        queued = await instagram.enqueue_private_reply(
            session,
            account_id=reply.account_id,
            comment_id=reply.comment_id,
            commented_at=reply.commented_at,
            text=decision.direct or "",
            ref=REF.format(reply_id=reply.id, part=DIRECT),
        )
    if not queued:
        # на этот коммент письмо уже стоит: второе Meta не примет
        reply.error_code = "already_replied"
        await _finish(session, reply, "answered", stage="send_failed")
        return
    await _finish(session, reply, "answered", stage="sending")


async def _failed(session: AsyncSession, job: _Job, code: str) -> None:
    """Нейросеть не ответила. Разовый сбой: повтор позже; остальное: failed."""
    reply = await _still_ours(session, job)
    if reply is None:
        return
    if code in TRANSIENT and reply.attempts < MAX_ATTEMPTS:
        reply.stage, reply.run_at = "queued", _now() + RETRY_DELAYS[reply.attempts - 1]
        reply.error_code = code
        await session.commit()
        log.warning("assistant.retry", reply_id=str(reply.id), code=code, attempts=reply.attempts)
        return
    reply.error_code = code
    await _finish(session, reply, "failed")


async def _still_ours(session: AsyncSession, job: _Job) -> Reply | None:
    """Строка под замком, если её всё ещё держит этот запуск. Зависшую могли
    вернуть в очередь и взять заново: тогда итог этого запуска не нужен."""
    reply = await repository.lock_reply(session, job.reply_id)
    if reply is None or reply.stage != "thinking" or reply.taken_at != job.taken_at:
        await session.commit()
        log.warning("assistant.result_dropped", reply_id=str(job.reply_id))
        return None
    return reply


async def _finish(session: AsyncSession, reply: Reply, outcome: str, stage: str = "done") -> None:
    """Итог на строку и в журнал, одной транзакцией с тем, что его вызвало."""
    reply.outcome, reply.stage, reply.decided_at = outcome, stage, _now()
    activity.record(
        session,
        f"assistant.{outcome}",
        account_id=reply.account_id,
        person_id=reply.person_id,
        comment_id=reply.comment_id,
        data={
            "assistant_id": str(reply.assistant_id),
            "reply_id": str(reply.id),
            "comment_reply": reply.comment_reply,
            "direct_reply": reply.direct_reply,
            "source": reply.source,
            "error_code": reply.error_code,
        },
    )
    await session.commit()
    log.info("assistant.decided", reply_id=str(reply.id), outcome=outcome)
