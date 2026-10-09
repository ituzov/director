# Сборка: ставим зависимости uv в .venv. В итоговый образ uv не попадает
FROM python:3.14-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# только манифесты: слой с зависимостями пересобирается, лишь когда меняется uv.lock
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# Итог: чистый Python, готовый .venv и код
FROM python:3.14-slim-trixie
# не root: если api взломают, у процесса не будет прав в контейнере
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=app:app . .
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
# миграции здесь не применяем: это отдельный сервис migrate в compose
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
