"""Ручки ключей приложения Meta: только владелец, секрет наружу не уходит."""

from datetime import UTC, datetime

import pytest

from app.config import settings
from app.core import crypto
from app.instagram import repository

APP_ID = "1571874044224461"
SECRET = "0123456789abcdef0123456789abcdef"
OTHER_SECRET = "f" * 32
OLD = datetime(2000, 1, 1, tzinfo=UTC)


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


async def stored_secret(session) -> str:
    return crypto.decrypt((await repository.get_meta_app(session)).app_secret_encrypted)


async def test_empty_until_saved(client, owner):
    r = await client.get("/instagram/app", headers=owner)
    assert (r.status_code, r.json()) == (200, None)


async def test_first_save(client, session, owner):
    r = await client.put(
        "/instagram/app", headers=owner, json={"app_id": APP_ID, "app_secret": SECRET}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["app_id"] == APP_ID
    assert "app_secret" not in body and "app_secret_encrypted" not in body
    assert len(body["verify_token"]) == 32
    assert await stored_secret(session) == SECRET

    assert (await client.get("/instagram/app", headers=owner)).json() == body


async def test_first_save_needs_secret(client, owner):
    r = await client.put("/instagram/app", headers=owner, json={"app_id": APP_ID})
    assert (r.status_code, r.json()["detail"]) == (422, "AppSecretRequired")


async def test_update_keeps_secret_and_verify_token(client, session, owner):
    first = await client.put(
        "/instagram/app", headers=owner, json={"app_id": APP_ID, "app_secret": SECRET}
    )
    r = await client.put("/instagram/app", headers=owner, json={"app_id": "42"})
    assert r.json()["app_id"] == "42"
    assert r.json()["verify_token"] == first.json()["verify_token"]
    assert await stored_secret(session) == SECRET


async def test_replace_secret(client, session, owner):
    await client.put("/instagram/app", headers=owner, json={"app_id": APP_ID, "app_secret": SECRET})
    await client.put(
        "/instagram/app", headers=owner, json={"app_id": APP_ID, "app_secret": OTHER_SECRET}
    )
    assert await stored_secret(session) == OTHER_SECRET


async def test_input_normalized(client, session, owner):
    r = await client.put(
        "/instagram/app",
        headers=owner,
        json={"app_id": f" {APP_ID} ", "app_secret": f" {SECRET.upper()}\n"},
    )
    assert r.json()["app_id"] == APP_ID
    assert await stored_secret(session) == SECRET


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"app_id": "abc"}, "app_id"),
        ({"app_secret": "IGAAWVnHIJo81BZAFlzMGE"}, "app_secret"),
        ({"app_secret": SECRET[:-1]}, "app_secret"),
    ],
)
async def test_bad_format(client, owner, change, field):
    r = await client.put(
        "/instagram/app", headers=owner, json={"app_id": APP_ID, "app_secret": SECRET} | change
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", field]


@pytest.mark.parametrize("method", ["get", "put"])
async def test_member_rejected(client, login_as, method):
    member = await login_as("member")
    r = await client.request(
        method, "/instagram/app", headers=member, json={"app_id": APP_ID, "app_secret": SECRET}
    )
    assert (r.status_code, r.json()["detail"]) == (403, "OwnerOnly")


async def test_no_token(client):
    assert (await client.get("/instagram/app")).status_code == 401


async def test_meta_urls(client, owner, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://1-2-3-4.sslip.io/")
    r = await client.put(
        "/instagram/app", headers=owner, json={"app_id": APP_ID, "app_secret": SECRET}
    )
    assert r.json()["webhook_url"] == "https://1-2-3-4.sslip.io/webhooks/instagram"
    assert r.json()["redirect_uri"] == "https://1-2-3-4.sslip.io/instagram/callback"
    assert r.json()["privacy_url"] == "https://1-2-3-4.sslip.io/privacy"


@pytest.mark.parametrize("public_url", [None, ""])
async def test_meta_urls_without_public_url(client, owner, monkeypatch, public_url):
    # в compose незаданная переменная приходит пустой строкой
    monkeypatch.setattr(settings, "public_url", public_url)
    r = await client.put(
        "/instagram/app", headers=owner, json={"app_id": APP_ID, "app_secret": SECRET}
    )
    assert r.json()["webhook_url"] is None


async def test_resave_moves_updated_at(client, session, owner):
    await client.put("/instagram/app", headers=owner, json={"app_id": APP_ID, "app_secret": SECRET})
    # тест целиком в одной транзакции, а now() в ней не движется: состарим время руками
    meta_app = await repository.get_meta_app(session)
    meta_app.updated_at = OLD
    await session.commit()

    r = await client.put("/instagram/app", headers=owner, json={"app_id": APP_ID})
    # время считает база и отдаёт в том же ответе: без лишнего запроса и без ошибки async
    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["updated_at"]) > OLD
