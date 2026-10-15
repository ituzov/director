<p align="center"><b>Director</b></p>
<p align="center">They drop a keyword in the comments and get a reply in DMs.</p>
<p align="center"><a href="docs/self-hosting.en.md">Install</a> · <a href="README.md">Русский</a></p>
<p align="center">
  <a href="https://github.com/ituzov/director/releases"><img src="https://img.shields.io/github/v/release/ituzov/director?include_prereleases" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/ituzov/director" alt="License"></a>
</p>

<p align="center"><img src=".github/assets/demo.en.gif" alt="Director" width="800"></p>

> Early 0.x version: breaking changes between versions are possible.

## What it is

Director replies to Instagram comments by keyword. Someone comments "guide"
under a post, Director replies in the comments and sends them a DM with a
button. They tap the button and get the guide. Followers and non-followers can
get different replies.

Director runs on your server through your own Meta app. Standard Access is
enough for your own accounts: no App Review, business verification or
registered company needed. Data, tokens and messages stay with you.

## Features

- Autoreplies: keywords under a post, a reply in the comments and in DMs
- Follow check: one reply for followers, another for everyone else
- A weekly funnel: from the comment to the delivered material
- A journal: which step each person is at, how many are waiting to tap or to
  follow, and why an autoreply did or didn't fire
- Multiple Instagram accounts in one install
- A queue that stays within Instagram limits (750 replies per hour per
  account) when a post goes viral
- Updates with a button in the admin panel, with a database backup and
  rollback if something goes wrong

## Install

You need a server with Ubuntu or Debian and a public IP:

```sh
curl -fsSL https://opendirector.dev/install.sh | sudo bash
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

## Contributing

How to set up development, check your changes and send a pull request is in
[CONTRIBUTING.en.md](CONTRIBUTING.en.md). Before your first PR, the bot will
ask you to accept the [CLA](CLA.md) once.

## Thanks

The admin panel is inspired by [Dokploy](https://github.com/Dokploy/dokploy):
we learned from them how to make self-hosting simple and a panel easy to read.
UI components come from [shadcn/ui](https://ui.shadcn.com).

## License

[AGPL-3.0](LICENSE)
