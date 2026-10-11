"""Запросы autoreplies к базе. Без бизнес-правил и без commit: транзакцией
владеет вызывающий."""

import uuid
from collections import defaultdict

from sqlalchemy import select
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
