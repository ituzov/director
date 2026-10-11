"""HTTP-ручки autoreplies. Тонкие: разобрать запрос, позвать сервис, собрать ответ."""

import uuid

from fastapi import APIRouter, Request, status
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
from app.autoreplies.schemas import AutoreplyForm, AutoreplyIn, AutoreplyOut, EnabledIn
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
