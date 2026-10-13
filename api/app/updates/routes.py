"""HTTP-ручки updates. Тонкие: позвать сервис, собрать ответ."""

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter

from app import identity
from app.updates import service
from app.updates.schemas import UpdatesOut

# без префикса версии API: в api ходит только наша админка, и они едут одним релизом
router = APIRouter(prefix="/updates", tags=["updates"])


def _http() -> httpx.AsyncClient:
    # в тестах подменяется: в сеть тесты не ходят
    return httpx.AsyncClient()


@router.get("")
async def get_updates(owner: identity.CurrentOwner) -> UpdatesOut:
    """Текущая версия и что доступно. Сайт недоступен: error в ответе, а не 5xx."""
    async with _http() as http:
        state = await service.check(http, datetime.now(UTC))
    return UpdatesOut.model_validate(state)
