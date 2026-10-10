"""HTTP-ручки instagram. Тонкие: разобрать запрос, позвать сервис, собрать ответ."""

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app import identity
from app.db import SessionDep
from app.instagram import service
from app.instagram.exceptions import AppSecretRequired, InstagramError
from app.instagram.schemas import MetaAppIn, MetaAppOut

router = APIRouter(prefix="/instagram", tags=["instagram"])

_STATUS = {
    AppSecretRequired: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


async def instagram_error_handler(request: Request, exc: InstagramError) -> JSONResponse:
    # detail это имя ошибки: по нему Next выбирает текст для человека
    return JSONResponse({"detail": type(exc).__name__}, status_code=_STATUS[type(exc)])


@router.get("/app")
async def get_meta_app(session: SessionDep, owner: identity.CurrentOwner) -> MetaAppOut | None:
    # None, пока ключи не вводили: админка покажет пустую форму
    meta_app = await service.get_meta_app(session)
    return MetaAppOut.model_validate(meta_app) if meta_app else None


@router.put("/app")
async def put_meta_app(
    body: MetaAppIn, session: SessionDep, owner: identity.CurrentOwner
) -> MetaAppOut:
    meta_app = await service.save_meta_app(session, app_id=body.app_id, app_secret=body.app_secret)
    return MetaAppOut.model_validate(meta_app)
