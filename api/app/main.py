"""Точка входа HTTP: собирает приложение из роутеров модулей.

Бизнес-логики здесь нет. CORS не нужен: браузер ходит только в web (BFF),
в api стучится сервер Next.
"""

from fastapi import FastAPI

from app import autoreplies, identity, instagram, updates
from app.config import settings
from app.core.logging import log_requests, setup_logging

# до создания приложения: uvicorn уже настроил свои логи, перехватываем их
setup_logging(settings.log_level, settings.log_json)

app = FastAPI(
    title="Director API",
    exception_handlers={
        identity.IdentityError: identity.identity_error_handler,
        instagram.InstagramError: instagram.instagram_error_handler,
        autoreplies.AutoreplyError: autoreplies.autoreply_error_handler,
    },
)
app.include_router(identity.router)
app.include_router(instagram.router)
app.include_router(instagram.webhook_router)
app.include_router(autoreplies.router)
app.include_router(updates.router)
app.middleware("http")(log_requests)


@app.get("/health")
def health() -> dict[str, str]:
    """Жив ли процесс. Для healthcheck в compose."""
    return {"status": "ok"}
