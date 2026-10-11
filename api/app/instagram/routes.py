"""HTTP-ручки instagram. Тонкие: разобрать запрос, позвать сервис, собрать ответ."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app import identity
from app.db import SessionDep
from app.instagram import service
from app.instagram.exceptions import AppSecretRequired, InstagramError
from app.instagram.models import MetaApp
from app.instagram.schemas import MetaAppIn, MetaAppOut

router = APIRouter(prefix="/instagram", tags=["instagram"])
# адрес вебхука постоянный и без префикса модуля: его владелец вписал в кабинет Meta
webhook_router = APIRouter(tags=["instagram"])

_STATUS = {
    AppSecretRequired: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


async def instagram_error_handler(request: Request, exc: InstagramError) -> JSONResponse:
    # detail это имя ошибки: по нему Next выбирает текст для человека
    return JSONResponse({"detail": type(exc).__name__}, status_code=_STATUS[type(exc)])


def _meta_app_out(meta_app: MetaApp) -> MetaAppOut:
    return MetaAppOut(
        app_id=meta_app.app_id,
        verify_token=meta_app.verify_token,
        updated_at=meta_app.updated_at,
        webhook_url=service.public_url(service.WEBHOOK_PATH),
        redirect_uri=service.public_url(service.OAUTH_CALLBACK_PATH),
        privacy_url=service.public_url(service.PRIVACY_PATH),
    )


@router.get("/app")
async def get_meta_app(session: SessionDep, owner: identity.CurrentOwner) -> MetaAppOut | None:
    # None, пока ключи не вводили: админка покажет пустую форму
    meta_app = await service.get_meta_app(session)
    return _meta_app_out(meta_app) if meta_app else None


@router.put("/app")
async def put_meta_app(
    body: MetaAppIn, session: SessionDep, owner: identity.CurrentOwner
) -> MetaAppOut:
    meta_app = await service.save_meta_app(session, app_id=body.app_id, app_secret=body.app_secret)
    return _meta_app_out(meta_app)


@webhook_router.get(service.WEBHOOK_PATH, response_class=PlainTextResponse)
async def verify_webhook(
    session: SessionDep,
    # Meta отдаёт число; эхо произвольной строки из запроса это заготовка для атаки
    challenge: Annotated[str, Query(alias="hub.challenge", pattern=r"^[0-9]{1,32}$")],
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
) -> str:
    if not await service.verify_webhook(session, mode=mode, token=token):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return challenge
