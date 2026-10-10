"""Точка входа HTTP: собирает приложение из роутеров модулей.

Бизнес-логики здесь нет. CORS не нужен: браузер ходит только в web (BFF),
в api стучится сервер Next.
"""

from fastapi import FastAPI

from app import identity, instagram

app = FastAPI(
    title="Director API",
    exception_handlers={
        identity.IdentityError: identity.identity_error_handler,
        instagram.InstagramError: instagram.instagram_error_handler,
    },
)
app.include_router(identity.router)
app.include_router(instagram.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Жив ли процесс. Для healthcheck в compose."""
    return {"status": "ok"}
