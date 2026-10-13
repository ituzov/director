"""HTTP-ручки updates. Тонкие: позвать сервис, собрать ответ."""

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app import identity
from app.updates import service
from app.updates.exceptions import UpdatesError
from app.updates.schemas import StatusOut, UpdateIn, UpdatesOut

# без префикса версии API: в api ходит только наша админка, и они едут одним релизом
router = APIRouter(prefix="/updates", tags=["updates"])


def _http() -> httpx.AsyncClient:
    # в тестах подменяется: в сеть тесты не ходят
    return httpx.AsyncClient()


async def updates_error_handler(request: Request, exc: UpdatesError) -> JSONResponse:
    # все отказы это «сейчас нельзя»; detail это имя ошибки, по нему Next выбирает текст
    return JSONResponse({"detail": type(exc).__name__}, status_code=status.HTTP_409_CONFLICT)


@router.get("")
async def get_updates(owner: identity.CurrentOwner) -> UpdatesOut:
    """Текущая версия и что доступно. Сайт недоступен: error в ответе, а не 5xx."""
    async with _http() as http:
        state = await service.check(http, datetime.now(UTC))
    return UpdatesOut.model_validate(state)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def request_update(body: UpdateIn, owner: identity.CurrentOwner) -> StatusOut:
    """Попросить хост обновиться. 202: обновлять будет хост, а не этот запрос."""
    async with _http() as http:
        result = await service.request_update(http, datetime.now(UTC), body.version)
    return StatusOut.model_validate(result)


@router.get("/status")
async def get_status(owner: identity.CurrentOwner) -> StatusOut:
    """Как идёт обновление. Во время перезапуска api ответа не будет: это нормально."""
    return StatusOut.model_validate(service.status(datetime.now(UTC)))
