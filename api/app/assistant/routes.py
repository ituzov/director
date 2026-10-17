"""HTTP-ручки assistant. Тонкие: разобрать запрос, позвать сервис, собрать ответ.
Смотрят все вошедшие, правит владелец: ассистент тратит его ключ к нейросети."""

import uuid

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app import identity
from app.assistant import service
from app.assistant.exceptions import (
    AccountUnavailable,
    AssistantArchived,
    AssistantConflict,
    AssistantError,
    AssistantNotFound,
    ConnectionMissing,
)
from app.assistant.schemas import AssistantForm, AssistantIn, AssistantOut, EnabledIn, TodayOut
from app.db import SessionDep

router = APIRouter(prefix="/assistants", tags=["assistant"])

_STATUS = {
    AssistantNotFound: status.HTTP_404_NOT_FOUND,
    AccountUnavailable: status.HTTP_409_CONFLICT,
    AssistantArchived: status.HTTP_409_CONFLICT,
    AssistantConflict: status.HTTP_409_CONFLICT,
    # ошибка поля «Подключение»: выбранное удалили в другой вкладке
    ConnectionMissing: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


async def assistant_error_handler(request: Request, exc: AssistantError) -> JSONResponse:
    # detail это имя ошибки: по нему Next выбирает текст для человека
    body: dict = {"detail": type(exc).__name__}
    if isinstance(exc, AssistantConflict):
        body["conflict"] = {
            "kind": exc.kind,
            "value": exc.value,
            "assistant": {"id": str(exc.assistant_id), "name": exc.name, "enabled": exc.enabled},
        }
    return JSONResponse(body, status_code=_STATUS[type(exc)])


def _out(full: service.Full) -> AssistantOut:
    a, binding = full.assistant, full.binding
    return AssistantOut(
        id=a.id,
        account_id=a.account_id,
        name=a.name,
        scope=a.scope,
        media_ids=full.media_ids,
        mode=a.mode,
        instruction=a.instruction,
        knowledge=a.knowledge,
        daily_limit=a.daily_limit,
        enabled=a.enabled,
        archived_at=a.archived_at,
        connection_id=binding.connection_id if binding else None,
        model=binding.model if binding else None,
        model_missing=binding.model_missing if binding else False,
        today=TodayOut(
            answered=full.today.get("answered", 0),
            unsure=full.today.get("unsure", 0),
            not_mine=full.today.get("not_mine", 0),
        ),
        updated_at=a.updated_at,
    )


@router.get("")
async def list_assistants(
    account_id: uuid.UUID,
    session: SessionDep,
    user: identity.CurrentUserRef,
    archived: bool = False,
) -> list[AssistantOut]:
    return [_out(f) for f in await service.list_for_account(session, account_id, archived=archived)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_assistant(
    body: AssistantIn, session: SessionDep, user: identity.CurrentOwner
) -> AssistantOut:
    return _out(await service.create(session, body, user))


@router.get("/{assistant_id}")
async def get_assistant(
    assistant_id: uuid.UUID, session: SessionDep, user: identity.CurrentUserRef
) -> AssistantOut:
    return _out(await service.get(session, assistant_id))


@router.put("/{assistant_id}")
async def update_assistant(
    assistant_id: uuid.UUID, body: AssistantForm, session: SessionDep, user: identity.CurrentOwner
) -> AssistantOut:
    return _out(await service.update(session, assistant_id, body))


@router.put("/{assistant_id}/enabled")
async def set_enabled(
    assistant_id: uuid.UUID, body: EnabledIn, session: SessionDep, user: identity.CurrentOwner
) -> AssistantOut:
    return _out(await service.set_enabled(session, assistant_id, body.enabled))


@router.post("/{assistant_id}/archive")
async def archive_assistant(
    assistant_id: uuid.UUID, session: SessionDep, user: identity.CurrentOwner
) -> AssistantOut:
    return _out(await service.archive(session, assistant_id))


@router.post("/{assistant_id}/unarchive")
async def unarchive_assistant(
    assistant_id: uuid.UUID, session: SessionDep, user: identity.CurrentOwner
) -> AssistantOut:
    return _out(await service.unarchive(session, assistant_id))
