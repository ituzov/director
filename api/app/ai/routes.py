"""HTTP-ручки ai: экран «Настройки → ИИ». Тонкие: разобрать запрос, позвать
сервис, собрать ответ. Ключ наружу не уходит, только последние символы."""

import uuid
from itertools import groupby

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app import identity
from app.ai import providers, service
from app.ai.exceptions import (
    AiCallFailed,
    AiError,
    BaseUrlNotAllowed,
    BaseUrlRequired,
    ConnectionNotFound,
    KeyInvalidChars,
    KeyRejected,
    KeyTooShort,
    ModelRequired,
    UnknownProvider,
)
from app.ai.models import Binding, Connection
from app.ai.schemas import (
    CheckedOut,
    ConnectionIn,
    ConnectionOut,
    KeyIn,
    NameIn,
    ProviderOut,
    TaskOut,
)
from app.db import SessionDep

router = APIRouter(prefix="/ai", tags=["ai"])

_STATUS = {
    UnknownProvider: status.HTTP_422_UNPROCESSABLE_CONTENT,
    BaseUrlRequired: status.HTTP_422_UNPROCESSABLE_CONTENT,
    BaseUrlNotAllowed: status.HTTP_422_UNPROCESSABLE_CONTENT,
    KeyTooShort: status.HTTP_422_UNPROCESSABLE_CONTENT,
    KeyInvalidChars: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # ничего не сохранено: владелец скорее скопировал ключ не целиком
    KeyRejected: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ModelRequired: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ConnectionNotFound: status.HTTP_404_NOT_FOUND,
    # ручки модель не зовут; на случай, если позовут
    AiCallFailed: status.HTTP_502_BAD_GATEWAY,
}


async def ai_error_handler(request: Request, exc: AiError) -> JSONResponse:
    # detail это имя ошибки: по нему Next выбирает текст для человека
    return JSONResponse({"detail": type(exc).__name__}, status_code=_STATUS[type(exc)])


def _tasks(bindings: list[Binding]) -> list[TaskOut]:
    tasks = []
    # bindings отсортированы по purpose: groupby собирает задачу целиком
    for purpose, group in groupby(bindings, lambda b: b.purpose):
        group = list(group)
        tasks.append(
            TaskOut(
                purpose=purpose,
                scopes=len(group),
                models=sorted({b.model for b in group}),
                model_missing=any(b.model_missing_at is not None for b in group),
            )
        )
    return tasks


def _out(connection: Connection, bindings: list[Binding]) -> ConnectionOut:
    return ConnectionOut(
        id=connection.id,
        provider=connection.provider,
        name=connection.name,
        key_hint=connection.key_hint,
        base_url=connection.base_url,
        checked_at=connection.checked_at,
        error_code=connection.error_code,
        error_at=connection.error_at,
        created_at=connection.created_at,
        tasks=_tasks(bindings),
    )


async def _card(session: SessionDep, connection: Connection) -> ConnectionOut:
    bindings = await service.bindings_by_connection(session, [connection.id])
    return _out(connection, bindings[connection.id])


async def _checked(session: SessionDep, checked: service.Checked) -> CheckedOut:
    return CheckedOut(
        connection=await _card(session, checked.connection), check=checked.error or "ok"
    )


@router.get("/providers")
async def list_providers(user: identity.CurrentUserRef) -> list[ProviderOut]:
    return [
        ProviderOut(kind=p.kind, needs_base_url=p.needs_base_url)
        for p in providers.REGISTRY.values()
    ]


@router.get("/connections")
async def list_connections(
    session: SessionDep, user: identity.CurrentUserRef
) -> list[ConnectionOut]:
    connections = await service.list_connections(session)
    bindings = await service.bindings_by_connection(session, [c.id for c in connections])
    return [_out(c, bindings[c.id]) for c in connections]


@router.post("/connections", status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionIn, session: SessionDep, user: identity.CanConnectAccounts
) -> CheckedOut:
    checked = await service.create_connection(
        session,
        provider=body.provider,
        name=body.name,
        key=body.key,
        base_url=body.base_url,
        created_by=user.id,
    )
    return await _checked(session, checked)


@router.put("/connections/{connection_id}/key")
async def replace_key(
    connection_id: uuid.UUID, body: KeyIn, session: SessionDep, user: identity.CanConnectAccounts
) -> CheckedOut:
    checked = await service.replace_key(session, connection_id, key=body.key)
    return await _checked(session, checked)


@router.post("/connections/{connection_id}/check")
async def recheck(
    connection_id: uuid.UUID, session: SessionDep, user: identity.CanConnectAccounts
) -> CheckedOut:
    return await _checked(session, await service.recheck(session, connection_id))


@router.patch("/connections/{connection_id}")
async def rename(
    connection_id: uuid.UUID, body: NameIn, session: SessionDep, user: identity.CanConnectAccounts
) -> ConnectionOut:
    connection = await service.rename(session, connection_id, name=body.name)
    return await _card(session, connection)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID, session: SessionDep, user: identity.CanConnectAccounts
) -> None:
    await service.delete_connection(session, connection_id)
