"""Посты аккаунта для формы: прямо из Meta, страницами по закладке, токен наружу
не уходит, ошибки Meta понятны форме."""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.activity.models import Event
from app.core import crypto
from app.instagram import graph, service
from app.instagram.models import Account

TOKEN = "IGAAsecret"
REEL = {
    "id": "18000000000000001",
    "caption": "Как забрать гайд",
    "media_type": "VIDEO",
    "media_product_type": "REELS",
    "thumbnail_url": "https://cdn/reel-thumb.jpg",
    "media_url": "https://cdn/reel.mp4",
    "permalink": "https://www.instagram.com/reel/x/",
    "timestamp": "2026-01-02T03:04:05+0000",
    "comments_count": 16,
}
CAROUSEL = {
    "id": "18000000000000002",
    "media_type": "CAROUSEL_ALBUM",
    "media_product_type": "FEED",
    "media_url": "https://cdn/first.jpg",
    "permalink": "https://www.instagram.com/p/y/",
    "timestamp": "2026-01-03T03:04:05+0000",
    "comments_count": 3,
}


class FakeMeta:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.response = httpx.Response(
            200,
            json={
                "data": [CAROUSEL, REEL],
                "paging": {
                    "cursors": {"before": "B", "after": "A1"},
                    "next": f"https://graph.instagram.com/v26.0/1/media?after=A1&access_token={TOKEN}",
                },
            },
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


@pytest.fixture
def meta(monkeypatch) -> FakeMeta:
    fake = FakeMeta()
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(service, "_http", lambda: httpx.AsyncClient(transport=transport))
    return fake


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


@pytest.fixture
async def account(session) -> Account:
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted=crypto.encrypt(TOKEN),
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()
    return account


def url(account) -> str:
    return f"/instagram/accounts/{account.id}/media"


async def test_first_page(client, owner, account, meta):
    r = await client.get(url(account), headers=owner)
    assert r.status_code == 200
    body = r.json()
    carousel, reel = body["items"]
    # у карусели миниатюра это первая картинка, у видео thumbnail_url
    assert (carousel["thumbnail"], carousel["type"], carousel["caption"]) == (
        "https://cdn/first.jpg",
        "FEED",
        None,
    )
    assert (reel["thumbnail"], reel["type"], reel["comments_count"]) == (
        "https://cdn/reel-thumb.jpg",
        "REELS",
        16,
    )
    assert body["next"] == "A1"

    [request] = meta.requests
    assert request.url.path == f"/{graph.VERSION}/me/media"
    assert request.url.params["fields"] == graph.MEDIA_FIELDS
    assert request.url.params["limit"] == "24"
    assert "after" not in request.url.params


async def test_token_never_leaves(client, owner, account, meta):
    r = await client.get(url(account), headers=owner)
    assert TOKEN not in r.text
    assert "graph.instagram.com" not in r.text


async def test_next_page_by_cursor(client, owner, account, meta):
    await client.get(url(account), headers=owner, params={"after": "A1"})
    assert meta.requests[0].url.params["after"] == "A1"


async def test_last_page(client, owner, account, meta):
    # курсор пришёл, а next нет: страница последняя
    meta.response = httpx.Response(
        200, json={"data": [REEL], "paging": {"cursors": {"before": "B", "after": "A2"}}}
    )
    r = await client.get(url(account), headers=owner)
    assert r.json()["next"] is None


async def test_no_posts(client, owner, account, meta):
    meta.response = httpx.Response(200, json={"data": []})
    r = await client.get(url(account), headers=owner)
    assert r.json() == {"items": [], "next": None}


@pytest.mark.parametrize(("status", "code"), [(500, 2), (400, 4)])
async def test_meta_error(client, owner, account, meta, status, code):
    meta.response = httpx.Response(status, json={"error": {"message": "x", "code": code}})
    r = await client.get(url(account), headers=owner)
    assert (r.status_code, r.json()["detail"]) == (502, "MetaUnavailable")


async def test_meta_down(client, owner, account, monkeypatch):
    def down(request):
        raise httpx.ConnectError("down")

    transport = httpx.MockTransport(down)
    monkeypatch.setattr(service, "_http", lambda: httpx.AsyncClient(transport=transport))
    r = await client.get(url(account), headers=owner)
    assert (r.status_code, r.json()["detail"]) == (502, "MetaUnavailable")


async def test_invalid_token_expires_account(client, owner, account, meta, session):
    meta.response = httpx.Response(400, json={"error": {"message": "x", "code": 190}})
    r = await client.get(url(account), headers=owner)
    assert (r.status_code, r.json()["detail"]) == (409, "AccountUnavailable")
    await session.refresh(account)
    assert (account.status, account.token_encrypted) == ("token_expired", None)
    assert [e.kind for e in await session.scalars(select(Event))] == ["account.token_expired"]


@pytest.mark.parametrize("status", [None, "disconnected"])
async def test_account_unavailable(client, owner, account, meta, session, status):
    if status:
        account.status, account.token_encrypted = status, None
        await session.commit()
        target = url(account)
    else:
        target = f"/instagram/accounts/{uuid.uuid7()}/media"
    r = await client.get(target, headers=owner)
    assert (r.status_code, r.json()["detail"]) == (409, "AccountUnavailable")
    assert meta.requests == []


async def test_cursor_too_long(client, owner, account, meta):
    r = await client.get(url(account), headers=owner, params={"after": "x" * 513})
    assert r.status_code == 422


async def test_anonymous_rejected(client, account, meta):
    assert (await client.get(url(account))).status_code == 401
