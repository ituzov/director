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
from app.assistant.models import Assistant, Reply
from app.assistant.service import ANSWER, day_start
from app.db import SessionLocal

log = structlog.get_logger("app.assistant")


@dataclass(frozen=True, slots=True)
class Taken:
    """Коммент взял ассистент: какой. Отвечать или промолчать, он решит позже."""

    assistant_id: uuid.UUID


async def handle_comment(session: AsyncSession, comment: instagram.CommentRef) -> Taken | None:
    """Коммент, который не взял ни один автоответ. None: отвечать некому."""
    if comment.parent_id is not None:
        # ответ на коммент, чаще всего под нашим же ответом: каждый такой давал бы
        # ещё одно сообщение в директ. Продолжение разговора потом
        return None
    assistant = await _owner(session, comment.account_id, comment.media_id)
    if assistant is None:
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


async def _owner(session: AsyncSession, account_id: uuid.UUID, media_id: str) -> Assistant | None:
    """Кто отвечает на коммент под постом: включённый частный ассистент поста,
    иначе включённый общий. Частный на паузе пост для других частных держит, а
    ответить пускает общего, как у автоответов: иначе пауза сделала бы пост немым."""
    own = await repository.post_holder(session, account_id, media_id)
    if own is not None and own.enabled:
        return own
    general = await repository.live_general(session, account_id, None)
    return general if general is not None and general.enabled else None


# на коммент сутками позже отвечать странно: такой остаётся без ответа (expired)
TOO_OLD = timedelta(hours=24)
# строка в thinking старше этого брошена упавшим worker. С запасом: ai.run это
# до ai.STEPS запросов (переспросы по схеме), каждый до 120 с, то есть до 10 минут
STUCK = timedelta(minutes=15)
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
    # пока коммент ждал, пост могли отдать другому ассистенту или поставить на паузу:
    # отвечает тот, кто хозяин сейчас
    owner = await _owner(session, reply.account_id, reply.media_id)
    if owner is None:
        await _finish(session, reply, "paused")
        return True
    reply.assistant_id = owner.id
    assistant = await repository.lock_assistant(session, owner.id)
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
    taken = await repository.taken_since(session, assistant.id, day_start(now), reply.id)
    if taken >= assistant.daily_limit:
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
    # ошибка прошлой попытки к этому решению не относится
    reply.error_code = None
    reply.source = decision.source
    if decision.decision != "answer":
        await _finish(session, reply, "unsure" if decision.decision == "unsure" else "not_mine")
        return
    reply.comment_reply, reply.direct_reply = decision.comment, decision.direct
    # отправка по режиму, с которым писала модель: владелец мог сменить его, пока
    # она думала, а текста для нового режима в ответе нет
    if job.brief.mode == "comment":
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


async def handle_send_result(session: AsyncSession, result: instagram.OutboxResult) -> None:
    """Итог отправки письма ассистента: стадия ответа и запись в журнал. Без
    commit: отчёт и отметку о нём коммитит instagram одной транзакцией. Чужие
    метки и ответы, которых уже нет, пропускаем."""
    parsed = _parse_ref(result.ref)
    if parsed is None:
        return
    reply_id, part = parsed
    reply = await repository.lock_reply(session, reply_id)
    if reply is None:
        return
    sent = result.outcome == "sent"
    activity.record(
        session,
        "assistant.sent" if sent else "assistant.send_failed",
        account_id=reply.account_id,
        person_id=reply.person_id,
        comment_id=reply.comment_id,
        data={"reply_id": str(reply.id), "part": part, "reason": result.reason},
        occurred_at=result.finished_at,
    )
    # строку двигает только первый отчёт: повтор и коммент в combo приходят, когда
    # она уже не в sending (коммент встаёт после ушедшего директа), и остаются
    # только в журнале
    if reply.stage != "sending":
        return
    if not sent:
        reply.stage, reply.error_code = "send_failed", result.reason or result.outcome
        return
    reply.stage = "sent"
    if reply.direct_reply is not None and reply.comment_reply is not None:
        # директ ушёл: теперь «подробно написали в директ» под комментом правда
        await instagram.enqueue_comment_reply(
            session,
            account_id=reply.account_id,
            comment_id=reply.comment_id,
            text=reply.comment_reply or "",
            ref=REF.format(reply_id=reply.id, part=COMMENT),
        )


def _parse_ref(ref: str) -> tuple[uuid.UUID, str] | None:
    prefix, _, rest = ref.partition(":")
    reply, _, part = rest.partition(":")
    if prefix != "assistant" or part not in (DIRECT, COMMENT):
        return None
    try:
        return uuid.UUID(reply), part
    except ValueError:
        return None
