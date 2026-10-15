"""HTTP-ручки autoreplies. Тонкие: разобрать запрос, позвать сервис, собрать ответ."""

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from app import identity
from app.autoreplies import service
from app.autoreplies.exceptions import (
    AccountUnavailable,
    AutoreplyArchived,
    AutoreplyConflict,
    AutoreplyError,
    AutoreplyNotFound,
)
from app.autoreplies.schemas import (
    AutoreplyCountsOut,
    AutoreplyForm,
    AutoreplyIn,
    AutoreplyOut,
    DeliveryOut,
    DeliveryPageOut,
    EnabledIn,
    HistoryOut,
    Stage,
    StageCountsOut,
    StatsOut,
    StepOut,
)
from app.db import SessionDep

router = APIRouter(prefix="/autoreplies", tags=["autoreplies"])

_STATUS = {
    AutoreplyNotFound: status.HTTP_404_NOT_FOUND,
    AccountUnavailable: status.HTTP_409_CONFLICT,
    AutoreplyArchived: status.HTTP_409_CONFLICT,
    AutoreplyConflict: status.HTTP_409_CONFLICT,
}


async def autoreply_error_handler(request: Request, exc: AutoreplyError) -> JSONResponse:
    # detail это имя ошибки: по нему Next выбирает текст для человека
    body: dict = {"detail": type(exc).__name__}
    if isinstance(exc, AutoreplyConflict):
        body["conflict"] = {
            "kind": exc.kind,
            "value": exc.value,
            "autoreply": {"id": str(exc.autoreply_id), "name": exc.name, "enabled": exc.enabled},
        }
    return JSONResponse(body, status_code=_STATUS[type(exc)])


def _out(full: service.Full) -> AutoreplyOut:
    a = full.autoreply
    return AutoreplyOut(
        id=a.id,
        account_id=a.account_id,
        name=a.name,
        scope=a.scope,
        media_ids=full.media_ids,
        keywords=full.keywords,
        intro_text=a.intro_text,
        button_text=a.button_text,
        reply_text=a.reply_text,
        follow_gate=a.follow_gate,
        not_following_text=a.not_following_text,
        comment_replies=a.comment_replies,
        comment_reply_mode=a.comment_reply_mode,
        enabled=a.enabled,
        archived_at=a.archived_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@router.get("")
async def list_autoreplies(
    account_id: uuid.UUID,
    session: SessionDep,
    user: identity.CurrentUserRef,
    archived: bool = False,
) -> list[AutoreplyOut]:
    return [_out(f) for f in await service.list_for_account(session, account_id, archived=archived)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_autoreply(
    body: AutoreplyIn, session: SessionDep, user: identity.CanConnectAccounts
) -> AutoreplyOut:
    return _out(await service.create(session, body, user))


# выше /{autoreply_id}: иначе «stats» разбирался бы как id
@router.get("/stats")
async def get_stats(
    account_id: uuid.UUID,
    session: SessionDep,
    user: identity.CurrentUserRef,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> StatsOut:
    """Воронка выдач аккаунта за days дней."""
    result = await service.stats(session, account_id, days=days)
    counts = [AutoreplyCountsOut(**asdict(c)) for c in result.by_autoreply]
    return StatsOut(
        triggered=result.triggered,
        sent=result.sent,
        clicked=result.clicked,
        delivered=result.delivered,
        undelivered=result.undelivered,
        top=counts[:5],
        by_autoreply=counts,
    )


# тоже выше /{autoreply_id}
@router.get("/history")
async def get_history(
    account_id: uuid.UUID,
    comment_id: Annotated[list[str], Query(max_length=100)],
    session: SessionDep,
    user: identity.CurrentUserRef,
) -> HistoryOut:
    """Что автоответы сделали с этими комментами: для строк ленты входящих."""
    comments: dict[str, list[StepOut]] = {}
    for s in await service.history(session, account_id, comment_id):
        step = asdict(s)
        comments.setdefault(step.pop("comment_id"), []).append(StepOut(**step))
    return HistoryOut(comments=comments)


# тоже выше /{autoreply_id}
@router.get("/deliveries")
async def list_deliveries(
    account_id: uuid.UUID,
    session: SessionDep,
    user: identity.CurrentUserRef,
    stage: Annotated[list[Stage] | None, Query()] = None,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DeliveryPageOut:
    """Выдачи аккаунта, свежие сверху; stage можно повторить: выдачи на любом из этапов."""
    page = await service.deliveries(session, account_id, stages=stage, before=before, limit=limit)
    return DeliveryPageOut(items=[DeliveryOut(**asdict(i)) for i in page.items], next=page.next)


@router.get("/deliveries/counts")
async def get_stage_counts(
    account_id: uuid.UUID, session: SessionDep, user: identity.CurrentUserRef
) -> StageCountsOut:
    return StageCountsOut(counts=await service.stage_counts(session, account_id))


@router.get("/{autoreply_id}")
async def get_autoreply(
    autoreply_id: uuid.UUID, session: SessionDep, user: identity.CurrentUserRef
) -> AutoreplyOut:
    return _out(await service.get(session, autoreply_id))


@router.put("/{autoreply_id}")
async def update_autoreply(
    autoreply_id: uuid.UUID,
    body: AutoreplyForm,
    session: SessionDep,
    user: identity.CanConnectAccounts,
) -> AutoreplyOut:
    return _out(await service.update(session, autoreply_id, body))


@router.put("/{autoreply_id}/enabled")
async def set_enabled(
    autoreply_id: uuid.UUID,
    body: EnabledIn,
    session: SessionDep,
    user: identity.CanConnectAccounts,
) -> AutoreplyOut:
    return _out(await service.set_enabled(session, autoreply_id, body.enabled))


@router.post("/{autoreply_id}/archive")
async def archive_autoreply(
    autoreply_id: uuid.UUID, session: SessionDep, user: identity.CanConnectAccounts
) -> AutoreplyOut:
    return _out(await service.archive(session, autoreply_id))


@router.post("/{autoreply_id}/unarchive")
async def unarchive_autoreply(
    autoreply_id: uuid.UUID, session: SessionDep, user: identity.CanConnectAccounts
) -> AutoreplyOut:
    return _out(await service.unarchive(session, autoreply_id))
