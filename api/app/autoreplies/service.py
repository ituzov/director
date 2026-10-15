"""Логика автоответов: настройка владельцем, кто отвечает под постом и что выдаём."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity, identity, instagram
from app.autoreplies import matching, replies, repository
from app.autoreplies.exceptions import (
    AccountUnavailable,
    AutoreplyArchived,
    AutoreplyConflict,
    AutoreplyNotFound,
)
from app.autoreplies.models import Autoreply, Delivery
from app.autoreplies.schemas import AutoreplyForm, AutoreplyIn

log = structlog.get_logger("app.autoreplies")

# кнопка автоответа: по префиксу нажатие узнаём среди кнопок других модулей
BUTTON_PREFIX = "ar:"
# метка исходящих автоответа: «autoreplies:<выдача>:<этап>»
REF_PREFIX = "autoreplies"
# этапы: директ с кнопкой, ответ под комментом, материал после нажатия
INTRO = "intro"
COMMENT = "comment"
MATERIAL = "material"


@dataclass(frozen=True, slots=True)
class Taken:
    """Событие взяли автоответы. autoreply_id: какой; None, если не определить
    (битая кнопка, кнопка удалённого автоответа, нажал не тот)."""

    autoreply_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class Full:
    """Автоответ вместе со словами и постами: всё, что нужно форме и карточке."""

    autoreply: Autoreply
    keywords: list[str]
    media_ids: list[str]


async def create(session: AsyncSession, form: AutoreplyIn, user: identity.UserRef) -> Full:
    account = await instagram.get_account(session, form.account_id)
    if account is None or account.status == "disconnected":
        raise AccountUnavailable
    await repository.lock_account(session, form.account_id)
    await _check_conflicts(
        session, form.account_id, form.scope, _words(form), form.media_ids, exclude_id=None
    )

    autoreply = Autoreply(
        account_id=form.account_id,
        created_by=user.id,
        **_fields(form),
    )
    repository.add_autoreply(session, autoreply)
    await session.flush()
    repository.add_keywords(session, autoreply.id, _words(form))
    repository.add_media(session, autoreply.id, form.media_ids)
    await session.commit()
    log.info("autoreply.created", autoreply_id=str(autoreply.id), account_id=str(form.account_id))
    return await get(session, autoreply.id)


async def update(session: AsyncSession, autoreply_id: uuid.UUID, form: AutoreplyForm) -> Full:
    """Сохранить форму целиком: слова и посты заменяются тем, что прислали."""
    autoreply = await _existing(session, autoreply_id)
    if autoreply.archived_at is not None:
        raise AutoreplyArchived
    await repository.lock_account(session, autoreply.account_id)
    words = _words(form)
    await _check_conflicts(
        session, autoreply.account_id, form.scope, words, form.media_ids, exclude_id=autoreply.id
    )
    for field, value in _fields(form).items():
        setattr(autoreply, field, value)
    # список вариантов могли переставить: старый номер указывал бы не туда
    autoreply.last_comment_reply = None
    autoreply.updated_at = func.now()
    await repository.replace_keywords(session, autoreply.id, words)
    await repository.replace_media(session, autoreply.id, form.media_ids)
    await session.commit()
    log.info("autoreply.updated", autoreply_id=str(autoreply.id))
    return await get(session, autoreply.id)


async def set_enabled(session: AsyncSession, autoreply_id: uuid.UUID, enabled: bool) -> Full:
    """Пауза и обратно. Конфликтов нет: выключенный и так держит свои слова и посты."""
    autoreply = await _existing(session, autoreply_id)
    if autoreply.archived_at is not None:
        raise AutoreplyArchived
    if autoreply.enabled != enabled:
        autoreply.enabled = enabled
        autoreply.updated_at = func.now()
        await session.commit()
        log.info("autoreply.enabled", autoreply_id=str(autoreply.id), enabled=enabled)
    return await get(session, autoreply.id)


async def archive(session: AsyncSession, autoreply_id: uuid.UUID) -> Full:
    """В архив: перестаёт отвечать и отпускает посты и слова. Повтор ничего не меняет."""
    autoreply = await _existing(session, autoreply_id)
    if autoreply.archived_at is None:
        autoreply.archived_at = func.now()
        await repository.set_media_archived(session, autoreply.id, True)
        await session.commit()
        log.info("autoreply.archived", autoreply_id=str(autoreply.id))
    return await get(session, autoreply.id)


async def unarchive(session: AsyncSession, autoreply_id: uuid.UUID) -> Full:
    """Из архива, если слова и посты за это время никто не занял."""
    autoreply = await _existing(session, autoreply_id)
    if autoreply.archived_at is not None:
        await repository.lock_account(session, autoreply.account_id)
        media_ids = (await repository.media_by_autoreply(session, [autoreply.id])).get(
            autoreply.id, []
        )
        await _check_conflicts(
            session,
            autoreply.account_id,
            autoreply.scope,
            await repository.keyword_pairs(session, autoreply.id),
            media_ids,
            exclude_id=autoreply.id,
        )
        autoreply.archived_at = None
        await repository.set_media_archived(session, autoreply.id, False)
        await session.commit()
        log.info("autoreply.unarchived", autoreply_id=str(autoreply.id))
    return await get(session, autoreply.id)


async def _existing(session: AsyncSession, autoreply_id: uuid.UUID) -> Autoreply:
    autoreply = await repository.get_autoreply(session, autoreply_id)
    if autoreply is None:
        raise AutoreplyNotFound
    return autoreply


async def get(session: AsyncSession, autoreply_id: uuid.UUID) -> Full:
    autoreply = await repository.get_autoreply(session, autoreply_id)
    if autoreply is None:
        raise AutoreplyNotFound
    # после commit время и флаги считала база: перечитываем строку
    await session.refresh(autoreply)
    [full] = await _with_details(session, [autoreply])
    return full


async def list_for_account(
    session: AsyncSession, account_id: uuid.UUID, *, archived: bool
) -> list[Full]:
    autoreplies = await repository.list_autoreplies(session, account_id, archived=archived)
    return await _with_details(session, autoreplies)


async def _with_details(session: AsyncSession, autoreplies: list[Autoreply]) -> list[Full]:
    ids = [a.id for a in autoreplies]
    words = await repository.words_by_autoreply(session, ids)
    media = await repository.media_by_autoreply(session, ids)
    return [Full(a, words.get(a.id, []), media.get(a.id, [])) for a in autoreplies]


async def _check_conflicts(
    session: AsyncSession,
    account_id: uuid.UUID,
    scope: str,
    words: list[tuple[str, str]],
    media_ids: list[str],
    *,
    exclude_id: uuid.UUID | None,
) -> None:
    """Общие не делят слова, частные не делят посты. Архивные никому не мешают,
    выключенные мешают: включат обратно, и конфликт всплывёт молча."""
    if scope == "all":
        by_normalized = {normalized: word for word, normalized in words}
        taken = await repository.taken_keyword(session, account_id, list(by_normalized), exclude_id)
        if taken:
            keyword, other = taken
            raise AutoreplyConflict(
                "keyword",
                value=by_normalized[keyword.normalized],
                autoreply_id=other.id,
                name=other.name,
                enabled=other.enabled,
            )
    else:
        taken_post = await repository.taken_media(session, media_ids, exclude_id)
        if taken_post:
            media_id, other = taken_post
            raise AutoreplyConflict(
                "post",
                value=media_id,
                autoreply_id=other.id,
                name=other.name,
                enabled=other.enabled,
            )


def _words(form: AutoreplyForm) -> list[tuple[str, str]]:
    return [(word, matching.normalize(word)) for word in form.keywords]


def _fields(form: AutoreplyForm) -> dict:
    """Поля самой строки автоответа: без слов и постов, они в своих таблицах."""
    return form.model_dump(exclude={"keywords", "media_ids", "account_id"})


async def handle_comment(session: AsyncSession, comment: instagram.CommentRef) -> Taken | None:
    """Коммент из входящих: выдать автоответ, если совпало слово.
    Taken: коммент наш, даже если повторный и отвечать не будем; None: не наш."""
    candidates = await _candidates(session, comment)
    match = matching.find_match(comment.text, candidates)
    if match is None:
        return None

    # под замком: выбор ответа по очереди не должен разойтись с соседним комментом
    autoreply = await repository.lock_autoreply(session, match.autoreply_id)
    reply_index, reply_text = _choose_comment_reply(autoreply, comment.username)
    delivery_id = await repository.add_delivery(
        session,
        autoreply_id=match.autoreply_id,
        account_id=comment.account_id,
        comment_id=comment.comment_id,
        media_id=comment.media_id,
        person_id=comment.person_id,
        keyword=match.keyword,
        # этап «отправляем» со времени коммента: как matched в журнале
        stage_at=comment.received_at,
        comment_reply=reply_text,
    )
    if delivery_id:
        # очередь вариантов сдвигаем, только если выдача правда новая, а не повтор
        if reply_index is not None:
            autoreply.last_comment_reply = reply_index
        await _enqueue_private_reply(session, comment, autoreply, delivery_id)
    activity.record(
        session,
        "autoreply.matched" if delivery_id else "autoreply.repeat_comment",
        account_id=comment.account_id,
        autoreply_id=match.autoreply_id,
        person_id=comment.person_id,
        comment_id=comment.comment_id,
        data={
            "keyword": match.keyword,
            "delivery_id": str(delivery_id) if delivery_id else None,
        },
        occurred_at=comment.received_at,
    )
    return Taken(match.autoreply_id)


async def _enqueue_private_reply(
    session: AsyncSession,
    comment: instagram.CommentRef,
    autoreply: Autoreply,
    delivery_id: uuid.UUID,
) -> None:
    """Директ с кнопкой на выдачу, в той же транзакции: решение и письмо ложатся вместе.
    Ответ под комментом ждёт, пока директ уйдёт (handle_send_result)."""
    await instagram.enqueue_private_reply(
        session,
        account_id=comment.account_id,
        comment_id=comment.comment_id,
        commented_at=comment.received_at,
        text=replies.fill(autoreply.intro_text, comment.username),
        button=instagram.Button(
            title=autoreply.button_text, payload=f"{BUTTON_PREFIX}{delivery_id}"
        ),
        ref=_ref(delivery_id, INTRO),
    )


def _choose_comment_reply(
    autoreply: Autoreply, username: str | None
) -> tuple[int | None, str | None]:
    """Номер и текст ответа под комментом с подставленным ником, ничего не меняя.
    (None, None), если вариантов нет."""
    index = replies.pick(
        len(autoreply.comment_replies),
        autoreply.last_comment_reply,
        autoreply.comment_reply_mode,
    )
    if index is None:
        return None, None
    return index, replies.fill(autoreply.comment_replies[index], username)


async def handle_postback(session: AsyncSession, postback: instagram.PostbackRef) -> Taken | None:
    """Нажатие кнопки автоответа: выдать материал. Taken: кнопка наша, даже если
    нажатие пропущено (уже выдано, выдачи нет); None: кнопка чужая."""
    if not postback.payload.startswith(BUTTON_PREFIX):
        return None
    try:
        delivery_id = uuid.UUID(postback.payload.removeprefix(BUTTON_PREFIX))
    except ValueError:
        log.warning("autoreply.bad_button")
        return Taken(None)
    delivery = await repository.get_delivery(session, delivery_id, lock=True)
    if delivery is None or (delivery.account_id, delivery.person_id) != (
        postback.account_id,
        postback.person_id,
    ):
        # автоответ удалили или нажал не тот, кому выдавали
        return Taken(None)
    # двойной тап отдельно не ловим: оба нажатия попадут в один раунд, и второе
    # письмо в очередь не ляжет. Порог по времени глушил осознанные нажатия
    delivery.last_click_at = postback.acted_at

    journal = {
        "account_id": delivery.account_id,
        "autoreply_id": delivery.autoreply_id,
        "person_id": delivery.person_id,
        "comment_id": delivery.comment_id,
        "data": {"delivery_id": str(delivery.id)},
        # по нашим часам, как отправки: иначе спешащие часы Meta переставят шаги
        "occurred_at": postback.received_at,
    }
    if delivery.delivered_at:
        # материал уже в переписке прямо над кнопкой
        activity.record(session, "autoreply.repeat_click", **journal)
        return Taken(delivery.autoreply_id)

    if delivery.clicked_at is None:
        delivery.clicked_at = postback.acted_at
    # нажал: материал (или просьба подписаться) ставится в очередь
    _move(delivery, "clicked", postback.received_at)
    # выключенный или архивный всё равно выдаёт: человеку пообещали, он нажал
    autoreply = await repository.get_autoreply(session, delivery.autoreply_id)
    gate = None
    if autoreply.follow_gate:
        # неподписанному та же кнопка: подпишется и нажмёт ещё раз
        button = instagram.Button(
            title=autoreply.button_text, payload=f"{BUTTON_PREFIX}{delivery.id}"
        )
        gate = (autoreply.not_following_text, button)
    await instagram.enqueue_message(
        session,
        account_id=delivery.account_id,
        recipient_id=delivery.person_id,
        acted_at=postback.acted_at,
        text=autoreply.reply_text,
        # одно письмо на раунд: пока оно в очереди, новые нажатия второе не поставят
        dedup_key=f"material:{delivery.id}:{delivery.gate_round}",
        ref=_ref(delivery.id, MATERIAL),
        if_not_following=gate,
        # Meta не дала проверить подписку: выдаём, а не гоняем человека по кругу
        if_unknown=instagram.FOLLOWING,
    )
    activity.record(session, "autoreply.clicked", **journal)
    return Taken(delivery.autoreply_id)


async def handle_send_result(session: AsyncSession, result: instagram.OutboxResult) -> None:
    """Итог отправки письма автоответа: этап в выдаче и запись в журнал.
    Чужие метки и выдачи, которых уже нет, пропускаем."""
    parsed = _parse_ref(result.ref)
    if parsed is None:
        return
    delivery_id, stage = parsed
    # под замком: раунд растёт, пока рядом может разбираться новое нажатие
    delivery = await repository.get_delivery(session, delivery_id, lock=True)
    if delivery is None:
        return

    data: dict = {"delivery_id": str(delivery.id), "stage": stage}
    if result.outcome != "sent":
        kind = "autoreply.send_failed"
        data |= {"outcome": result.outcome, "reason": result.reason}
        if stage == INTRO:
            _move(delivery, "dm_failed", result.finished_at)
        if stage == MATERIAL:
            _move(delivery, "material_failed", result.finished_at)
            # материал не ушёл, а ключ его письма занят навсегда: новое нажатие
            # начнёт новый раунд, иначе оно не встанет в очередь
            delivery.gate_round += 1
    elif stage == INTRO:
        delivery.sent_at = func.now()
        _move(delivery, "waiting_click", result.finished_at)
        kind = "autoreply.sent"
        # директ ушёл, теперь правда «отправили в директ». Не ушёл: ответа не будет
        if delivery.comment_reply:
            await instagram.enqueue_comment_reply(
                session,
                account_id=delivery.account_id,
                comment_id=delivery.comment_id,
                text=delivery.comment_reply,
                ref=_ref(delivery.id, COMMENT),
            )
    elif stage == COMMENT:
        delivery.commented_at = func.now()
        kind = "autoreply.commented"
    elif stage == MATERIAL and result.variant == instagram.NOT_FOLLOWING:
        # ушла просьба подписаться: следующее нажатие начнёт новый раунд
        delivery.gate_round += 1
        _move(delivery, "follow_asked", result.finished_at)
        kind = "autoreply.follow_asked"
    elif stage == MATERIAL:
        delivery.delivered_at = func.now()
        _move(delivery, "delivered", result.finished_at)
        kind = "autoreply.delivered"
        if result.variant is not None:
            # following или unknown: подписку проверили или Meta не дала проверить
            data["follow"] = result.variant
    else:
        return
    activity.record(
        session,
        kind,
        account_id=delivery.account_id,
        autoreply_id=delivery.autoreply_id,
        person_id=delivery.person_id,
        comment_id=delivery.comment_id,
        data=data,
        # отчёт мог опоздать: в журнале время отправки, иначе «нажал» встал бы раньше директа
        occurred_at=result.finished_at,
    )


def _move(delivery: Delivery, stage: str, at: datetime) -> None:
    """Где выдача сейчас. Двигает только событие не старше того, что поставило текущий
    этап: запоздалый отчёт об отправке не вернёт нажавшего в «ждём нажатия». Получил
    материал: окончательно."""
    if delivery.stage == "delivered" or at < delivery.stage_at:
        return
    delivery.stage, delivery.stage_at = stage, at


def _ref(delivery_id: uuid.UUID, stage: str) -> str:
    return f"{REF_PREFIX}:{delivery_id}:{stage}"


def _parse_ref(ref: str) -> tuple[uuid.UUID, str] | None:
    prefix, _, rest = ref.partition(":")
    delivery, _, stage = rest.partition(":")
    if prefix != REF_PREFIX or not stage:
        return None
    try:
        return uuid.UUID(delivery), stage
    except ValueError:
        return None


async def _candidates(
    session: AsyncSession, comment: instagram.CommentRef
) -> list[matching.Candidate]:
    """Частный этого поста, если он включён; иначе общие аккаунта. Пост забран целиком,
    а выключенный частный его отпускает: иначе пауза сделала бы пост немым."""
    own = await repository.live_autoreply_for_media(session, comment.account_id, comment.media_id)
    if own is not None and own.enabled:
        autoreplies = [own]
    else:
        autoreplies = await repository.enabled_general_autoreplies(session, comment.account_id)
    keywords = await repository.keywords_by_autoreply(session, [a.id for a in autoreplies])
    return [matching.Candidate(a.id, tuple(keywords.get(a.id, ()))) for a in autoreplies]


@dataclass(frozen=True, slots=True)
class AutoreplyCounts:
    id: uuid.UUID
    name: str
    triggered: int
    delivered: int
    last_at: datetime


@dataclass(frozen=True, slots=True)
class Stats:
    # сработало, ушёл директ с кнопкой, нажали кнопку, получили материал
    triggered: int
    sent: int
    clicked: int
    delivered: int
    # отправки автоответов, которые так и не ушли
    undelivered: int
    # все срабатывавшие за период, чаще первыми: топ обзора и цифры на карточках
    by_autoreply: list[AutoreplyCounts]


async def stats(session: AsyncSession, account_id: uuid.UUID, *, days: int) -> Stats:
    """Сводка аккаунта за последние days дней, прямо по выдачам."""
    since = await session.scalar(select(func.now() - timedelta(days=days)))
    triggered, sent, clicked, delivered = await repository.delivery_counts(
        session, account_id, since=since
    )
    counts = await repository.autoreply_counts(session, account_id, since=since)
    undelivered = await instagram.count_undelivered(
        session, account_id, since=since, ref_prefix=f"{REF_PREFIX}:"
    )
    return Stats(
        triggered=triggered,
        sent=sent,
        clicked=clicked,
        delivered=delivered,
        undelivered=undelivered,
        by_autoreply=[AutoreplyCounts(*row) for row in counts],
    )


# шаг выдачи по событию журнала; неудачная отправка отдельно, по этапу
_STEPS = {
    "autoreply.matched": "matched",
    "autoreply.repeat_comment": "repeat_comment",
    "autoreply.sent": "dm_sent",
    "autoreply.commented": "commented",
    "autoreply.clicked": "clicked",
    "autoreply.repeat_click": "repeat_click",
    "autoreply.follow_asked": "follow_asked",
    "autoreply.delivered": "delivered",
}
_FAILED = {INTRO: "dm_failed", COMMENT: "comment_failed", MATERIAL: "material_failed"}


@dataclass(frozen=True, slots=True)
class Step:
    """Что автоответ сделал с комментом, кодом: текст для человека подбирает web."""

    comment_id: str
    step: str
    at: datetime
    autoreply_id: uuid.UUID | None
    # слово, на которое сработал автоответ
    keyword: str | None = None
    # неудачная отправка: failed или expired, и код ошибки Meta или наша причина
    outcome: str | None = None
    reason: str | None = None
    # у материала: following или unknown, если Meta не дала проверить подписку
    follow: str | None = None


async def history(
    session: AsyncSession, account_id: uuid.UUID, comment_ids: list[str]
) -> list[Step]:
    """Шаги выдачи по комментам аккаунта, по порядку. Чужие события журнала пропускаем."""
    steps = []
    for e in await activity.comment_history(session, account_id, comment_ids):
        if e.kind == "autoreply.send_failed":
            # этапа нет в data: неудача остаётся в цепочке, только без подробностей
            step = _FAILED.get(e.data.get("stage"), "send_failed")
        else:
            step = _STEPS.get(e.kind)
        # comment_id есть всегда, искали по нему; проверка для типа Step.comment_id
        if step is None or e.comment_id is None:
            continue
        steps.append(
            Step(
                e.comment_id,
                step,
                e.occurred_at,
                e.autoreply_id,
                keyword=e.data.get("keyword"),
                outcome=e.data.get("outcome"),
                reason=e.data.get("reason"),
                follow=e.data.get("follow"),
            )
        )
    return steps


# этапы выдачи, как их хранит delivery.stage (там же проверка в базе)
STAGES = (
    "sending",
    "waiting_click",
    "dm_failed",
    "clicked",
    "follow_asked",
    "material_failed",
    "delivered",
)


@dataclass(frozen=True, slots=True)
class DeliveryItem:
    """Выдача для списка «Выдач»: кому, на какой коммент, каким автоответом и где сейчас."""

    id: uuid.UUID
    comment_id: str
    person_id: str
    # ник и текст из входящих instagram; None: там коммента уже нет
    username: str | None
    text: str | None
    autoreply_id: uuid.UUID
    autoreply_name: str
    keyword: str
    stage: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryPage:
    items: list[DeliveryItem]
    # закладка следующей страницы: id последней выдачи; None, если дальше пусто
    next: uuid.UUID | None


async def deliveries(
    session: AsyncSession,
    account_id: uuid.UUID,
    *,
    stages: list[str] | None,
    before: uuid.UUID | None,
    limit: int,
) -> DeliveryPage:
    """Выдачи аккаунта страницами, свежие сверху; stages: только на этих этапах."""
    rows = await repository.deliveries_page(session, account_id, stages, before=before, limit=limit)
    more = len(rows) > limit
    rows = rows[:limit]
    texts = await instagram.comment_texts(session, account_id, [d.comment_id for d, _ in rows])

    def nick(d: Delivery) -> str | None:
        seen = texts.get(d.comment_id)
        return seen.username if seen else None

    # коммента нет во входящих или в нём нет ника: ник по другим комментам человека
    missing = sorted({d.person_id for d, _ in rows if not nick(d)})
    nicks = await instagram.usernames(session, account_id, missing)
    items = []
    for d, name in rows:
        seen = texts.get(d.comment_id)
        items.append(
            DeliveryItem(
                id=d.id,
                comment_id=d.comment_id,
                person_id=d.person_id,
                username=nick(d) or nicks.get(d.person_id),
                text=seen.text if seen else None,
                autoreply_id=d.autoreply_id,
                autoreply_name=name,
                keyword=d.keyword,
                stage=d.stage,
                created_at=d.created_at,
            )
        )
    return DeliveryPage(items=items, next=rows[-1][0].id if more else None)


async def stage_counts(session: AsyncSession, account_id: uuid.UUID) -> dict[str, int]:
    """Сколько выдач сейчас на каждом этапе, для вкладок; этап без выдач с нулём."""
    counts = await repository.stage_counts(session, account_id)
    return {stage: counts.get(stage, 0) for stage in STAGES}
