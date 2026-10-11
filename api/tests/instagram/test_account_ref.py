"""Справка аккаунта для соседей: без токена, None для чужого id."""

import dataclasses
import uuid

from app import instagram
from app.instagram.models import Account


async def test_ref_without_token(session):
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted="секрет",
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()

    ref = await instagram.get_account(session, account.id)
    assert ref == instagram.AccountRef(
        id=account.id, ig_user_id="17841400000000000", username="shop", status="active"
    )
    assert "token" not in {f.name for f in dataclasses.fields(ref)}


async def test_unknown_account(session):
    assert await instagram.get_account(session, uuid.uuid7()) is None
