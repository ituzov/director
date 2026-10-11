"""Логика автоответов: кто отвечает под постом и что выдаём."""

from sqlalchemy.ext.asyncio import AsyncSession

from app import activity, instagram
from app.autoreplies import matching, repository


async def handle_comment(session: AsyncSession, comment: instagram.CommentRef) -> bool:
    """Коммент из входящих: выдать автоответ, если совпало слово.
    True: коммент наш, даже если повторный и отвечать не будем."""
    candidates = await _candidates(session, comment)
    match = matching.find_match(comment.text, candidates)
    if match is None:
        return False

    delivery_id = await repository.add_delivery(
        session,
        autoreply_id=match.autoreply_id,
        account_id=comment.account_id,
        comment_id=comment.comment_id,
        media_id=comment.media_id,
        person_id=comment.person_id,
        keyword=match.keyword,
    )
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
    return True


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
