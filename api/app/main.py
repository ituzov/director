"""Точка входа HTTP: собирает приложение из роутеров модулей.

Бизнес-логики здесь нет. CORS не нужен: браузер ходит только в web (BFF),
в api стучится сервер Next.
"""

from fastapi import FastAPI

app = FastAPI(title="Director API")


@app.get("/health")
def health() -> dict[str, str]:
    """Жив ли процесс. Для healthcheck в compose и Dokploy."""
    return {"status": "ok"}
