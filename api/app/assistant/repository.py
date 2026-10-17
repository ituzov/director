"""Запросы assistant к базе. Без бизнес-правил и без commit: транзакцией владеет сервис."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import Assistant, AssistantMedia, Reply


async def lock_account(session: AsyncSession, account_id: uuid.UUID) -> None:
    """Сохранения ассистентов одного аккаунта по очереди до конца транзакции:
    иначе два одновременных пройдут проверку конфликтов мимо друг друга. Своё
    зерно хэша: замок автоответов того же аккаунта этот не держит."""
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(account_id), 1)))
    )


def add_assistant(session: AsyncSession, assistant: Assistant) -> None:
    session.add(assistant)


async def get_assistant(session: AsyncSession, assistant_id: uuid.UUID) -> Assistant | None:
    return await session.get(Assistant, assistant_id)


async def list_assistants(
    session: AsyncSession, account_id: uuid.UUID, *, archived: bool
) -> list[Assistant]:
    archive = Assistant.archived_at.is_not(None) if archived else Assistant.archived_at.is_(None)
    return list(
        await session.scalars(
            select(Assistant)
            .where(Assistant.account_id == account_id, archive)
            # общий первым, потом частные по имени
            .order_by(Assistant.scope, Assistant.name, Assistant.id)
        )
    )


async def live_general(
    session: AsyncSession, account_id: uuid.UUID, exclude_id: uuid.UUID | None
) -> Assistant | None:
    """Живой общий ассистент аккаунта, кроме этого (на паузе тоже живой)."""
    query = select(Assistant).where(
        Assistant.account_id == account_id,
        Assistant.scope == "all",
        Assistant.archived_at.is_(None),
    )
    if exclude_id is not None:
        query = query.where(Assistant.id != exclude_id)
    return await session.scalar(query.limit(1))


async def taken_media(
    session: AsyncSession, media_ids: list[str], exclude_id: uuid.UUID | None
) -> tuple[str, Assistant] | None:
    """Пост из списка у другого живого частного ассистента."""
    query = (
        select(AssistantMedia.media_id, Assistant)
        .join(Assistant)
        .where(AssistantMedia.media_id.in_(media_ids), AssistantMedia.archived.is_(False))
        .limit(1)
    )
    if exclude_id is not None:
        query = query.where(Assistant.id != exclude_id)
    row = (await session.execute(query)).first()
    return (row[0], row[1]) if row else None


def add_media(session: AsyncSession, assistant_id: uuid.UUID, media_ids: list[str]) -> None:
    session.add_all(AssistantMedia(assistant_id=assistant_id, media_id=m) for m in media_ids)


async def replace_media(
    session: AsyncSession, assistant_id: uuid.UUID, media_ids: list[str]
) -> None:
    await session.execute(delete(AssistantMedia).where(AssistantMedia.assistant_id == assistant_id))
    add_media(session, assistant_id, media_ids)


async def set_media_archived(
    session: AsyncSession, assistant_id: uuid.UUID, archived: bool
) -> None:
    """Флаг архива у постов: на нём стоит частичный уникальный индекс."""
    await session.execute(
        update(AssistantMedia)
        .where(AssistantMedia.assistant_id == assistant_id)
        .values(archived=archived)
    )


async def media_by_assistant(
    session: AsyncSession, assistant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    rows = await session.execute(
        select(AssistantMedia.assistant_id, AssistantMedia.media_id)
        .where(AssistantMedia.assistant_id.in_(assistant_ids))
        .order_by(AssistantMedia.media_id)
    )
    media: dict[uuid.UUID, list[str]] = defaultdict(list)
    for assistant_id, media_id in rows:
        media[assistant_id].append(media_id)
    return media


async def outcomes_since(
    session: AsyncSession, assistant_ids: list[uuid.UUID], since: datetime
) -> dict[uuid.UUID, dict[str, int]]:
    """Итоги прочитанных с этого момента по ассистентам: счётчики «сегодня».
    По индексу (assistant_id, taken_at), а не пересчётом журнала."""
    rows = await session.execute(
        select(Reply.assistant_id, Reply.outcome, func.count())
        .where(Reply.assistant_id.in_(assistant_ids), Reply.taken_at >= since)
        .group_by(Reply.assistant_id, Reply.outcome)
    )
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    for assistant_id, outcome, count in rows:
        if outcome is not None:
            counts[assistant_id][outcome] = count
    return counts


async def post_holder(
    session: AsyncSession, account_id: uuid.UUID, media_id: str
) -> Assistant | None:
    """Живой частный ассистент поста этого аккаунта (на паузе тоже живой)."""
    return await session.scalar(
        select(Assistant)
        .join(AssistantMedia)
        .where(
            Assistant.account_id == account_id,
            AssistantMedia.media_id == media_id,
            AssistantMedia.archived.is_(False),
        )
        .limit(1)
    )


async def add_reply(session: AsyncSession, **fields) -> uuid.UUID | None:
    """Коммент в очередь ассистента. None: этот коммент уже в очереди (повтор
    вебхука), вторая строка не встаёт."""
    return await session.scalar(
        insert(Reply)
        .values(**fields)
        .on_conflict_do_nothing(index_elements=["comment_id"])
        .returning(Reply.id)
    )


async def release_stuck(session: AsyncSession, older_than: datetime) -> int:
    """Взятые и брошенные посреди запроса к нейросети (worker упал): обратно в
    очередь. Попытка уже засчитана при взятии."""
    result = await session.execute(
        update(Reply)
        .where(Reply.stage == "thinking", Reply.taken_at < older_than)
        .values(stage="queued", run_at=func.now())
    )
    return result.rowcount


async def claim_reply(session: AsyncSession, now: datetime) -> Reply | None:
    """Следующий коммент к ответу, запертый до конца транзакции. Чужие запертые
    пропускаем (SKIP LOCKED): каждый коммент берёт один цикл."""
    return await session.scalar(
        select(Reply)
        .where(Reply.stage == "queued", Reply.run_at <= now)
        .order_by(Reply.run_at, Reply.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


async def lock_person(session: AsyncSession, account_id: uuid.UUID, person_id: str) -> None:
    """Комменты одного человека по очереди: взятия его комментов ждут друг друга
    до конца транзакции. Своё зерно хэша, не пересекается с замком аккаунта."""
    key = f"{account_id}:{person_id}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 2))))


async def person_busy(session: AsyncSession, reply: Reply) -> bool:
    """Другой коммент этого человека сейчас у нейросети."""
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(Reply)
            .where(
                Reply.account_id == reply.account_id,
                Reply.person_id == reply.person_id,
                Reply.stage == "thinking",
                Reply.id != reply.id,
            )
        )
    )


async def lock_assistant(session: AsyncSession, assistant_id: uuid.UUID) -> Assistant | None:
    """Ассистент под замком: предел считаем и отмечаем «прочитал» одним действием,
    соседний цикл подождёт. Значения перечитываются из базы."""
    return await session.scalar(
        select(Assistant)
        .where(Assistant.id == assistant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def taken_since(
    session: AsyncSession, assistant_id: uuid.UUID, since: datetime, exclude_id: uuid.UUID
) -> int:
    """Сколько других комментов ассистент прочитал с этого момента: предел в
    сутки. Этот коммент не считаем: при повтор после сбоя он уже прочитан и иначе
    упёрся бы в предел сам о себя."""
    return await session.scalar(
        select(func.count())
        .select_from(Reply)
        .where(
            Reply.assistant_id == assistant_id,
            Reply.taken_at >= since,
            Reply.id != exclude_id,
        )
    )


async def lock_reply(session: AsyncSession, reply_id: uuid.UUID) -> Reply | None:
    return await session.scalar(
        select(Reply)
        .where(Reply.id == reply_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


# вкладки журнала: что в каждую попадает. Не ответил: и сбой до решения, и ответ,
# который написали, но он не дошёл
TAB_FILTERS = {
    "answered": lambda: and_(Reply.outcome == "answered", Reply.stage != "send_failed"),
    "unsure": lambda: Reply.outcome == "unsure",
    "not_mine": lambda: Reply.outcome == "not_mine",
    "missed": lambda: or_(
        Reply.outcome.in_(("failed", "limit", "expired", "paused")),
        Reply.stage == "send_failed",
    ),
}


async def replies_page(
    session: AsyncSession,
    account_id: uuid.UUID,
    tab: str | None,
    *,
    before: uuid.UUID | None,
    limit: int,
) -> list[tuple[Reply, str]]:
    """Ответы аккаунта с названием ассистента, свежие сверху. before: старше этого
    ответа. На одну больше limit: видно, есть ли дальше."""
    query = (
        select(Reply, Assistant.name)
        .join(Assistant, Assistant.id == Reply.assistant_id)
        .where(Reply.account_id == account_id)
    )
    if tab is not None:
        query = query.where(TAB_FILTERS[tab]())
    if before is not None:
        anchor = await session.get(Reply, before)
        # закладка чужого аккаунта резала бы список по чужому времени: считаем её неизвестной
        if anchor is None or anchor.account_id != account_id:
            return []
        query = query.where(tuple_(Reply.created_at, Reply.id) < (anchor.created_at, anchor.id))
    rows = await session.execute(
        query.order_by(Reply.created_at.desc(), Reply.id.desc()).limit(limit + 1)
    )
    return [(reply, name) for reply, name in rows.all()]


async def outcome_counts(
    session: AsyncSession, account_id: uuid.UUID
) -> list[tuple[str | None, str, int]]:
    """Сколько ответов аккаунта на каждой паре итог и стадия: из неё считаются вкладки."""
    rows = await session.execute(
        select(Reply.outcome, Reply.stage, func.count())
        .where(Reply.account_id == account_id)
        .group_by(Reply.outcome, Reply.stage)
    )
    return [(outcome, stage, count) for outcome, stage, count in rows.all()]
