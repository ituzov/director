<p align="center"><b>Director</b></p>
<p align="center">They drop a keyword in the comments and get a reply in DMs.</p>
<p align="center"><a href="README.md">Русский</a></p>

> Under active development. One-command install is not ready yet.

## What it is

Director replies to Instagram comments by keyword. Someone comments "guide"
under a post, Director replies in the comments and sends them a DM with a
button. They tap the button and get the guide. Followers and non-followers can
get different replies.

It runs on your server through your own Meta app. Data, tokens and messages
stay with you.

## Features

- Campaigns: a post, keywords, a reply in the comments and in DMs
- Follow check: one reply for followers, another for everyone else
- Multiple Instagram accounts in one install
- Users and roles: owner, members, access to specific accounts
- A queue that stays within Instagram limits (750 replies per hour per
  account) when a post goes viral

## Why self-hosted

Each install runs through its own Meta app. Standard Access is enough for
your own accounts: no App Review, business verification or registered company
needed.

## Stack

FastAPI, Postgres, Next.js, Caddy. All in docker compose.

## Development

```sh
docker compose -f docker-compose.dev.yml up -d   # Postgres for development
cd api && cp .env.example .env && uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload             # http://localhost:8000
uv run pytest                                    # includes module boundaries

cd web && npm install && npm run dev             # http://localhost:3000
```

## License

[AGPL-3.0](LICENSE)
