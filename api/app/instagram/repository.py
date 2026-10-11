"""Запросы instagram к базе. Без бизнес-правил и без commit: транзакцией
владеет сервис."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.instagram.models import InboxEvent, MetaApp


async def get_meta_app(session: AsyncSession) -> MetaApp | None:
    # строка всегда одна, с id = 1
    return await session.get(MetaApp, 1)


def add_meta_app(
    session: AsyncSession, *, app_id: str, app_secret_encrypted: str, verify_token: str
) -> MetaApp:
    meta_app = MetaApp(
        app_id=app_id, app_secret_encrypted=app_secret_encrypted, verify_token=verify_token
    )
    session.add(meta_app)
    return meta_app


async def add_inbox_events(session: AsyncSession, rows: list[dict]) -> int:
    """Положить события во входящие. Повторы (тот же dedup_key) молча пропускаются.
    Возвращает, сколько легло новых."""
    if not rows:
        return 0
    result = await session.execute(
        insert(InboxEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[InboxEvent.dedup_key])
        .returning(InboxEvent.id)
    )
    return len(result.all())
