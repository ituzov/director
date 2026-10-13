# Contributing to Director

Thanks for wanting to help. Found a bug or want a new feature: open an issue
first. A big change is better discussed before the code, so it doesn't drift
away from where the project is heading.

[Русский](CONTRIBUTING.md)

## Development

```sh
docker compose -f docker-compose.dev.yml up -d   # Postgres for development
cd api && cp .env.example .env && uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload             # http://localhost:8000

cd web && npm install && npm run dev             # http://localhost:3000
```

The backend is a modular monolith: a package per domain in `api/app/`, and
modules reach each other only through the module's `__init__.py`. The
boundaries and conventions are in
[docs/development/modules.md](docs/development/modules.md) (in Russian), read
it before your first new module.

## Before a pull request

In `api`:

```sh
uv run pytest            # tests, including module boundaries
uv run ruff check . && uv run ruff format --check .
uv run lint-imports
```

In `web`:

```sh
npx next build && npx tsc --noEmit && npx eslint . && npx prettier --check .
```

Check a new test by breaking it: break what it guards and make sure it turns
red.

User-facing texts come in two languages: Russian in `web/messages/ru.json` and
English with the same meaning in `en.json`.

## Commits

One finished idea per commit. Format `type(module): what was done`, for example
`fix(autoreplies): comment reply after the direct message`. Types: feat, fix,
perf, refactor, test, docs, ci, build, chore. A breaking change is marked with
`!`: `feat(instagram)!: …`. The description can be in English.

## Contributor License Agreement (CLA)

Before your first pull request, accept the [CLA](CLA.md) once. You keep the
copyright in your code, and the project gets the right to distribute it under
other licenses besides AGPL-3.0. Without it, the project couldn't change or add
a license without asking everyone who ever sent code.

The bot will comment on your first PR. Reply with:

```
I have read the CLA Document and I hereby sign the CLA
```

The signature is remembered for all your future PRs.
