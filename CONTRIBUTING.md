# Как помочь Директору

Спасибо, что хотите помочь. Нашли баг или хотите новую возможность: сначала
откройте issue. Большую доработку лучше обсудить до кода, чтобы она не
разошлась с тем, куда идёт проект.

[English](CONTRIBUTING.en.md)

## Разработка

```sh
docker compose -f docker-compose.dev.yml up -d   # Postgres для разработки
cd api && cp .env.example .env && uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload             # http://localhost:8000

cd web && npm install && npm run dev             # http://localhost:3000
```

Бэкенд это модульный монолит: пакет на домен в `api/app/`, соседи ходят друг к
другу только через `__init__.py` модуля. Границы и договорённости описаны в
[docs/development/modules.md](docs/development/modules.md), прочитайте до
первого нового модуля.

## Перед pull request

В `api`:

```sh
uv run pytest            # тесты, включая границы модулей
uv run ruff check . && uv run ruff format --check .
uv run lint-imports
```

В `web`:

```sh
npx next build && npx tsc --noEmit && npx eslint . && npx prettier --check .
```

Новый тест проверьте поломкой: сломайте то, что он охраняет, и убедитесь, что
он покраснел.

Тексты для людей пишем на двух языках: русский в `web/messages/ru.json`,
английский тем же смыслом в `en.json`.

## Коммиты

Одна законченная идея на коммит. Формат `тип(модуль): что сделано`, например
`fix(autoreplies): ответ под комментом после директа`. Типы: feat, fix, perf,
refactor, test, docs, ci, build, chore. Ломающее изменение помечается `!`:
`feat(instagram)!: …`.

## Соглашение с участником (CLA)

Перед первым pull request нужно один раз принять [CLA](CLA.md). Авторские
права на ваш код остаются у вас, а проект получает право распространять его
и под другими лицензиями, кроме AGPL-3.0. Без этого проект не сможет поменять
или дополнить лицензию, не спросив каждого, кто когда-либо прислал код.

Бот сам напишет в вашем первом PR. Ответьте комментарием:

```
I have read the CLA Document and I hereby sign the CLA
```

Подпись запомнится для всех следующих PR.
