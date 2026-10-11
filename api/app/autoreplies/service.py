"""Логика автоответов: настройка владельцем, кто отвечает под постом и что выдаём."""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app import activity, identity, instagram
from app.autoreplies import matching, repository
from app.autoreplies.exceptions import (
    AccountUnavailable,
    AutoreplyArchived,
    AutoreplyConflict,
    AutoreplyNotFound,
)
from app.autoreplies.models import Autoreply
from app.autoreplies.schemas import AutoreplyForm, AutoreplyIn

log = structlog.get_logger("app.autoreplies")


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
