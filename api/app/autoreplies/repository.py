"""Запросы autoreplies к базе. Без бизнес-правил и без commit: транзакцией
владеет вызывающий."""

import uuid
from collections import defaultdict

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoreplies.models import Autoreply, AutoreplyMedia, Delivery, Keyword


async def live_autoreply_for_media(
    session: AsyncSession, account_id: uuid.UUID, media_id: str
) -> Autoreply | None:
    """Частный автоответ поста, не архивный. Включён ли он, решает сервис.
    Архив смотрим по автоответу: флаг в постах только для уникального индекса."""
    return await session.scalar(
        select(Autoreply)
        .join(AutoreplyMedia)
        .where(AutoreplyMedia.media_id == media_id)
        .where(Autoreply.account_id == account_id, Autoreply.archived_at.is_(None))
    )


async def enabled_general_autoreplies(
    session: AsyncSession, account_id: uuid.UUID
) -> list[Autoreply]:
    return list(
        await session.scalars(
            select(Autoreply)
            .where(Autoreply.account_id == account_id, Autoreply.scope == "all")
            .where(Autoreply.enabled.is_(True), Autoreply.archived_at.is_(None))
            .order_by(Autoreply.created_at)
        )
    )


async def keywords_by_autoreply(
    session: AsyncSession, autoreply_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Нормализованные слова кандидатов одним запросом."""
    rows = await session.execute(
        select(Keyword.autoreply_id, Keyword.normalized).where(
            Keyword.autoreply_id.in_(autoreply_ids)
        )
    )
    keywords: dict[uuid.UUID, list[str]] = defaultdict(list)
    for autoreply_id, normalized in rows:
        keywords[autoreply_id].append(normalized)
    return keywords


async def add_delivery(
    session: AsyncSession,
    *,
    autoreply_id: uuid.UUID,
    account_id: uuid.UUID,
    comment_id: str,
    media_id: str,
    person_id: str,
    keyword: str,
) -> uuid.UUID | None:
    """Новая выдача. None: уже выдавали (тот же человек под тем же постом или тот же
    коммент). Одним запросом: между проверкой и вставкой нет щели для второго worker."""
    return await session.scalar(
        insert(Delivery)
        .values(
            autoreply_id=autoreply_id,
            account_id=account_id,
            comment_id=comment_id,
            media_id=media_id,
            person_id=person_id,
            keyword=keyword,
        )
        .on_conflict_do_nothing()
        .returning(Delivery.id)
    )


async def lock_account(session: AsyncSession, account_id: uuid.UUID) -> None:
    """Сохранения автоответов одного аккаунта по очереди до конца транзакции:
    иначе два одновременных пройдут проверку конфликтов мимо друг друга."""
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(account_id), 0)))
    )


async def taken_keyword(
    session: AsyncSession,
    account_id: uuid.UUID,
    normalized: list[str],
    exclude_id: uuid.UUID | None,
) -> tuple[Keyword, Autoreply] | None:
    """Слово из списка у другого живого общего автоответа аккаунта."""
    query = (
        select(Keyword, Autoreply)
        .join(Autoreply)
        .where(Autoreply.account_id == account_id, Autoreply.scope == "all")
        .where(Autoreply.archived_at.is_(None), Keyword.normalized.in_(normalized))
        .order_by(Keyword.id)
        .limit(1)
    )
    if exclude_id is not None:
        query = query.where(Autoreply.id != exclude_id)
    row = (await session.execute(query)).first()
    return (row[0], row[1]) if row else None


async def taken_media(
    session: AsyncSession, media_ids: list[str], exclude_id: uuid.UUID | None
) -> tuple[str, Autoreply] | None:
    """Пост из списка у другого живого частного автоответа."""
    query = (
        select(AutoreplyMedia.media_id, Autoreply)
        .join(Autoreply)
        .where(AutoreplyMedia.media_id.in_(media_ids), AutoreplyMedia.archived.is_(False))
        .limit(1)
    )
    if exclude_id is not None:
        query = query.where(Autoreply.id != exclude_id)
    row = (await session.execute(query)).first()
    return (row[0], row[1]) if row else None


def add_autoreply(session: AsyncSession, autoreply: Autoreply) -> None:
    session.add(autoreply)


def add_keywords(
    session: AsyncSession, autoreply_id: uuid.UUID, words: list[tuple[str, str]]
) -> None:
    """Слова в порядке ввода: (как ввёл, нормализованное)."""
    session.add_all(
        Keyword(autoreply_id=autoreply_id, word=word, normalized=normalized)
        for word, normalized in words
    )


def add_media(session: AsyncSession, autoreply_id: uuid.UUID, media_ids: list[str]) -> None:
    session.add_all(AutoreplyMedia(autoreply_id=autoreply_id, media_id=m) for m in media_ids)


async def get_autoreply(session: AsyncSession, autoreply_id: uuid.UUID) -> Autoreply | None:
    return await session.get(Autoreply, autoreply_id)


async def list_autoreplies(
    session: AsyncSession, account_id: uuid.UUID, *, archived: bool
) -> list[Autoreply]:
    archive = Autoreply.archived_at.is_not(None) if archived else Autoreply.archived_at.is_(None)
    return list(
        await session.scalars(
            select(Autoreply)
            .where(Autoreply.account_id == account_id, archive)
            .order_by(Autoreply.created_at.desc())
        )
    )


async def words_by_autoreply(
    session: AsyncSession, autoreply_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """Слова как ввёл владелец, в порядке ввода (uuid7 растёт со временем)."""
    rows = await session.execute(
        select(Keyword.autoreply_id, Keyword.word)
        .where(Keyword.autoreply_id.in_(autoreply_ids))
        .order_by(Keyword.id)
    )
    words: dict[uuid.UUID, list[str]] = defaultdict(list)
    for autoreply_id, word in rows:
        words[autoreply_id].append(word)
    return words


async def media_by_autoreply(
    session: AsyncSession, autoreply_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    rows = await session.execute(
        select(AutoreplyMedia.autoreply_id, AutoreplyMedia.media_id)
        .where(AutoreplyMedia.autoreply_id.in_(autoreply_ids))
        .order_by(AutoreplyMedia.media_id)
    )
    media: dict[uuid.UUID, list[str]] = defaultdict(list)
    for autoreply_id, media_id in rows:
        media[autoreply_id].append(media_id)
    return media


async def keyword_pairs(session: AsyncSession, autoreply_id: uuid.UUID) -> list[tuple[str, str]]:
    """Слова автоответа: (как ввёл, нормализованное), в порядке ввода."""
    rows = await session.execute(
        select(Keyword.word, Keyword.normalized)
        .where(Keyword.autoreply_id == autoreply_id)
        .order_by(Keyword.id)
    )
    return [(word, normalized) for word, normalized in rows]


async def replace_keywords(
    session: AsyncSession, autoreply_id: uuid.UUID, words: list[tuple[str, str]]
) -> None:
    await session.execute(delete(Keyword).where(Keyword.autoreply_id == autoreply_id))
    add_keywords(session, autoreply_id, words)


async def replace_media(
    session: AsyncSession, autoreply_id: uuid.UUID, media_ids: list[str]
) -> None:
    await session.execute(delete(AutoreplyMedia).where(AutoreplyMedia.autoreply_id == autoreply_id))
    add_media(session, autoreply_id, media_ids)


async def set_media_archived(
    session: AsyncSession, autoreply_id: uuid.UUID, archived: bool
) -> None:
    """Флаг архива у постов: на нём стоит частичный уникальный индекс."""
    await session.execute(
        update(AutoreplyMedia)
        .where(AutoreplyMedia.autoreply_id == autoreply_id)
        .values(archived=archived)
    )


async def lock_autoreply(session: AsyncSession, autoreply_id: uuid.UUID) -> Autoreply:
    """Автоответ под замком до конца транзакции: выбор варианта ответа и запись
    прошлого номера одним действием, второй worker подождёт."""
    return await session.scalar(
        select(Autoreply)
        .where(Autoreply.id == autoreply_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def get_delivery(session: AsyncSession, delivery_id: uuid.UUID) -> Delivery | None:
    return await session.get(Delivery, delivery_id)
