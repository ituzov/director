"""Ответ 422 на запрос, который не прошёл схему.

Стандартный ответ FastAPI повторяет присланное значение (поле input), а в
формах лежат секреты: ключ провайдера, секрет приложения Meta. Тело ответа
идёт через Next, и одного лога ошибки там хватило бы, чтобы секрет попал в
лог. Оставляем, где и что не так, без самого значения.
"""

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)
