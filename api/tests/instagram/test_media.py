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


async def test_page_size(client, owner, account, meta):
    # форма просит 8: два ряда в окне выбора
    await client.get(url(account), headers=owner, params={"limit": 8})
    assert meta.requests[0].url.params["limit"] == "8"


@pytest.mark.parametrize("limit", [0, 51])
async def test_page_size_bounds(client, owner, account, meta, limit):
    r = await client.get(url(account), headers=owner, params={"limit": limit})
    assert r.status_code == 422
    assert meta.requests == []


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


# Выбранные посты по id: каждый отдельным запросом к Meta


class FakeMetaById:
    """Отвечает по id из пути: пост, ошибка или «нет такого»."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.posts: dict[str, httpx.Response] = {
            REEL["id"]: httpx.Response(200, json=REEL),
            CAROUSEL["id"]: httpx.Response(200, json=CAROUSEL),
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        media_id = request.url.path.rsplit("/", 1)[-1]
        # так Meta отвечает про удалённый или чужой пост
        missing = {"error": {"message": "x", "code": 100, "error_subcode": 33}}
        return self.posts.get(media_id, httpx.Response(400, json=missing))


@pytest.fixture
def meta_by_id(monkeypatch) -> FakeMetaById:
    fake = FakeMetaById()
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(service, "_http", lambda: httpx.AsyncClient(transport=transport))
    return fake


def selected(account) -> str:
    return f"/instagram/accounts/{account.id}/media/selected"


async def test_selected_found(client, owner, account, meta_by_id):
    ids = [REEL["id"], CAROUSEL["id"]]
    r = await client.get(selected(account), headers=owner, params={"ids": ids})
    assert r.status_code == 200
    body = r.json()
    assert [m["id"] for m in body["items"]] == ids
    assert body["items"][0]["thumbnail"] == "https://cdn/reel-thumb.jpg"
    assert body["missing"] == []

    request = meta_by_id.requests[0]
    assert request.url.path == f"/{graph.VERSION}/{REEL['id']}"
    assert request.url.params["fields"] == graph.MEDIA_FIELDS
    assert TOKEN not in r.text


async def test_selected_missing(client, owner, account, meta_by_id):
    # пост удалили, а автоответ на нём ещё висит: форма покажет «пост удалён»
    gone = "18000000000000009"
    r = await client.get(selected(account), headers=owner, params={"ids": [REEL["id"], gone]})
    assert r.status_code == 200
    assert [m["id"] for m in r.json()["items"]] == [REEL["id"]]
    assert r.json()["missing"] == [gone]


async def test_selected_duplicates_asked_once(client, owner, account, meta_by_id):
    r = await client.get(selected(account), headers=owner, params={"ids": [REEL["id"]] * 2})
    assert len(r.json()["items"]) == 1
    assert len(meta_by_id.requests) == 1


async def test_selected_meta_error(client, owner, account, meta_by_id):
    meta_by_id.posts[CAROUSEL["id"]] = httpx.Response(500, json={"error": {"code": 2}})
    ids = [REEL["id"], CAROUSEL["id"]]
    r = await client.get(selected(account), headers=owner, params={"ids": ids})
    assert (r.status_code, r.json()["detail"]) == (502, "MetaUnavailable")


async def test_selected_token_expired_wins(client, owner, account, meta_by_id, session):
    # один запрос упал сбоем Meta, другой истёкшим токеном: важнее токен
    meta_by_id.posts[REEL["id"]] = httpx.Response(500, json={"error": {"code": 2}})
    meta_by_id.posts[CAROUSEL["id"]] = httpx.Response(400, json={"error": {"code": 190}})
    ids = [REEL["id"], CAROUSEL["id"]]
    r = await client.get(selected(account), headers=owner, params={"ids": ids})
    assert (r.status_code, r.json()["detail"]) == (409, "AccountUnavailable")
    await session.refresh(account)
    assert account.status == "token_expired"


async def test_selected_meta_down(client, owner, account, monkeypatch):
    def down(request):
        raise httpx.ConnectError("down")

    transport = httpx.MockTransport(down)
    monkeypatch.setattr(service, "_http", lambda: httpx.AsyncClient(transport=transport))
    r = await client.get(selected(account), headers=owner, params={"ids": [REEL["id"]]})
    assert (r.status_code, r.json()["detail"]) == (502, "MetaUnavailable")


@pytest.mark.parametrize(
    "ids",
    [
        [],
        # id встаёт в путь запроса к Meta: только цифры
        ["me"],
        ["../me/media"],
        [str(10**17 + i) for i in range(51)],
    ],
)
async def test_selected_bad_ids(client, owner, account, meta_by_id, ids):
    r = await client.get(selected(account), headers=owner, params={"ids": ids})
    assert r.status_code == 422
    assert meta_by_id.requests == []


async def test_selected_anonymous_rejected(client, account, meta_by_id):
    r = await client.get(selected(account), params={"ids": [REEL["id"]]})
    assert r.status_code == 401
