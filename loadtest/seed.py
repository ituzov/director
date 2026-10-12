"""Тестовые данные для нагрузки: приложение Meta с известным секретом, фейковый
аккаунт и автоответ на «гайд». Кодом самого api: секреты в базе шифруются SECRET_KEY.

Из /opt/director: docker compose exec -T api python < loadtest/seed.py
Только на тестовом сервере: заменяет ключи приложения Meta.
"""

import asyncio
import uuid

from sqlalchemy import select

from app import identity
from app.autoreplies import service as autoreplies
from app.autoreplies.schemas import AutoreplyIn
from app.core import crypto
from app.db import SessionLocal
from app.instagram.models import Account, MetaApp

# тем же секретом k6 подписывает вебхуки (webhooks.js)
APP_SECRET = "loadtest-secret"
# id аккаунта в entry.id вебхука: такие же цифры, как у Instagram
IG_USER_ID = "17841499999999999"


async def main() -> None:
    async with SessionLocal() as session:
        app = await session.get(MetaApp, 1)
        if app is None:
            app = MetaApp(app_id="1", app_secret_encrypted="", verify_token="loadtest")
            session.add(app)
        app.app_secret_encrypted = crypto.encrypt(APP_SECRET)

        account = await session.scalar(select(Account).where(Account.ig_user_id == IG_USER_ID))
        if account is None:
            account = Account(
                ig_user_id=IG_USER_ID,
                username="loadtest",
                token_encrypted=crypto.encrypt("loadtest-token"),
                connected_by=uuid.uuid7(),
            )
            session.add(account)
        await session.commit()

        existing = await autoreplies.list_for_account(session, account.id, archived=False)
        if not existing:
            owner = identity.UserRef(id=uuid.uuid7(), role="owner", can_connect_accounts=True)
            form = AutoreplyIn(
                account_id=account.id,
                name="Нагрузка",
                scope="all",
                keywords=["гайд"],
                intro_text="{username}, держи 👇",
                button_text="Получить",
                reply_text="https://example.com/guide",
                comment_replies=["Отправили в директ!", "Лови в директе 👌"],
            )
            await autoreplies.create(session, form, owner)
        print(f"account={account.id} ig_user_id={IG_USER_ID} autoreplies={len(existing) or 1}")


asyncio.run(main())
