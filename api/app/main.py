"""Точка входа HTTP: собирает приложение из роутеров модулей.

Бизнес-логики здесь нет. CORS не нужен: браузер ходит только в web (BFF),
в api стучится сервер Next.
"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app import ai, assistant, autoreplies, identity, instagram, updates
from app.config import settings
from app.core.logging import log_requests, setup_logging
from app.core.validation import validation_error_handler

# до создания приложения: uvicorn уже настроил свои логи, перехватываем их
setup_logging(settings.log_level, settings.log_json)

app = FastAPI(
    title="Director API",
    exception_handlers={
        RequestValidationError: validation_error_handler,
        identity.IdentityError: identity.identity_error_handler,
        instagram.InstagramError: instagram.instagram_error_handler,
        autoreplies.AutoreplyError: autoreplies.autoreply_error_handler,
        updates.UpdatesError: updates.updates_error_handler,
        ai.AiError: ai.ai_error_handler,
        assistant.AssistantError: assistant.assistant_error_handler,
    },
)
app.include_router(identity.router)
app.include_router(instagram.router)
app.include_router(instagram.webhook_router)
app.include_router(autoreplies.router)
app.include_router(updates.router)
app.include_router(ai.router)
app.include_router(assistant.router)
app.middleware("http")(log_requests)


@app.get("/health")
def health() -> dict[str, str]:
    """Жив ли процесс. Для healthcheck в compose."""
    return {"status": "ok"}
