<p align="center"><b>Director</b></p>
<p align="center">They drop a keyword in the comments and get a reply in DMs.</p>
<p align="center"><a href="docs/self-hosting.en.md">Install</a> · <a href="README.md">Русский</a></p>

<p align="center"><img src=".github/assets/demo.en.gif" alt="Director" width="800"></p>

> Early 0.x version: breaking changes between versions are possible. The
> first release, 0.1.0, is on its way, and the install command will work from it.

## What it is

Director replies to Instagram comments by keyword. Someone comments "guide"
under a post, Director replies in the comments and sends them a DM with a
button. They tap the button and get the guide. Followers and non-followers can
get different replies.

Director runs on your server through your own Meta app. Standard Access is
enough for your own accounts: no App Review, business verification or
registered company needed. Data, tokens and messages stay with you.

## Features

- Campaigns: a post, keywords, a reply in the comments and in DMs
- Follow check: one reply for followers, another for everyone else
- Multiple Instagram accounts in one install
- A queue that stays within Instagram limits (750 replies per hour per
  account) when a post goes viral
- One-command updates with a database backup and rollback if something goes
  wrong

## Install

You need a server with Ubuntu or Debian and a public IP:

```sh
curl -fsSL https://github.com/ituzov/director/releases/latest/download/install.sh | sudo bash
```

In a couple of minutes the script prints a link to the first sign-in, already
over HTTPS. Server requirements, your own domain, updates and backups are in
the [install guide](docs/self-hosting.en.md).

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
