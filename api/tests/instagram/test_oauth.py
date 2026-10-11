"""Подключение аккаунта через вход Instagram: пропуск, цепочка запросов к Meta, запись."""

import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import func, select
from structlog.testing import capture_logs

from app.config import settings
from app.core import crypto, signing
from app.instagram import graph, service
from app.instagram.models import Account

URL = "/instagram/oauth/url"
CALLBACK = "/instagram/oauth/callback"
IG_USER_ID = "17841400000000000"
LONG_TOKEN = "IGAAlong"
# текст ошибки Meta: в лог не попадает
LEAK = "leaked-request-part"


class FakeMeta:
    """Meta в тестах: отвечает на четыре запроса входа и запоминает, что у неё просили."""

    def __init__(self, username: str = "shop", fail_on: str | None = None) -> None:
        self.username = username
        self.fail_on = fail_on
        self.subscribed: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(graph.OAUTH):
            step, body = (
                "exchange_code",
                {
                    "data": [
                        {
                            "access_token": "short",
                            "user_id": IG_USER_ID,
                            "permissions": ",".join(service.SCOPES),
                        }
                    ]
                },
            )
        elif request.url.path == "/access_token":
            step, body = "long_lived_token", {"access_token": LONG_TOKEN, "expires_in": 5183944}
        elif request.url.path.endswith("/me"):
            step, body = "get_me", {"user_id": IG_USER_ID, "username": self.username}
        else:
            step = "subscribe"
            self.subscribed = request.url.params["subscribed_fields"].split(",")
            body = {"success": True}
        if step == self.fail_on:
            return httpx.Response(400, json={"error": {"message": LEAK, "code": 190}})
        return httpx.Response(200, json=body)


@pytest.fixture(autouse=True)
def public_url(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://director.test")


@pytest.fixture
async def owner(login_as, session):
    headers = await login_as("owner")
    await service.save_meta_app(session, app_id="1000000000000099", app_secret="a" * 32)
    return headers


def meta(monkeypatch, fake: FakeMeta) -> FakeMeta:
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(service, "_http", lambda: httpx.AsyncClient(transport=transport))
    return fake


async def start(client, headers) -> str:
    """Начать вход и вернуть state из адреса Instagram."""
    r = await client.get(URL, headers=headers)
    return parse_qs(urlparse(r.json()["url"]).query)["state"][0]


async def test_url(client, owner):
    r = await client.get(URL, headers=owner)
    url = urlparse(r.json()["url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == service.AUTHORIZE_URL
    assert query["client_id"] == "1000000000000099"
    assert query["redirect_uri"] == "https://director.test/instagram/callback"
    assert query["response_type"] == "code"
    assert query["scope"].split(",") == service.SCOPES
    assert query["state"]


async def test_url_needs_meta_app(client, login_as):
    r = await client.get(URL, headers=await login_as("owner"))
    assert (r.status_code, r.json()["detail"]) == (409, "MetaAppRequired")


async def test_url_needs_public_url(client, owner, monkeypatch):
    monkeypatch.setattr(settings, "public_url", None)
    r = await client.get(URL, headers=owner)
    assert (r.status_code, r.json()["detail"]) == (409, "PublicUrlRequired")


async def test_connect(client, session, owner, monkeypatch):
    fake = meta(monkeypatch, FakeMeta())
    state = await start(client, owner)
    r = await client.post(CALLBACK, headers=owner, json={"code": "abc", "state": state})
    assert r.status_code == 200
    body = r.json()
    assert (body["ig_user_id"], body["username"], body["status"]) == (IG_USER_ID, "shop", "active")
    assert not any("token" in key for key in body)

    # аккаунт лёг commit-ом: откат его не снимает
    await session.rollback()
    account = await session.scalar(select(Account))
    assert crypto.decrypt(account.token_encrypted) == LONG_TOKEN
    assert account.token_expires_at is not None
    assert fake.subscribed == service.FIELDS


async def test_reconnect_revives_same_row(client, session, owner, monkeypatch):
    meta(monkeypatch, FakeMeta(username="old"))
    await client.post(
        CALLBACK, headers=owner, json={"code": "a", "state": await start(client, owner)}
    )
    account = await session.scalar(select(Account))
    account.status, account.token_encrypted = "disconnected", None
    await session.commit()

    meta(monkeypatch, FakeMeta(username="new"))
    r = await client.post(
        CALLBACK, headers=owner, json={"code": "b", "state": await start(client, owner)}
    )
    assert (r.json()["username"], r.json()["status"]) == ("new", "active")
    assert await session.scalar(select(func.count()).select_from(Account)) == 1


@pytest.mark.parametrize(
    "state",
    [
        "forged",
        # подпись наша, но выдана другому пользователю
        signing.sign({"u": str(uuid.uuid7()), "n": "x"}, purpose=service.STATE_PURPOSE),
        # другой пользователь, другое назначение
        signing.sign({"u": "x"}, purpose="other"),
    ],
)
async def test_bad_state(client, session, owner, monkeypatch, state):
    meta(monkeypatch, FakeMeta())
    r = await client.post(CALLBACK, headers=owner, json={"code": "abc", "state": state})
    assert (r.status_code, r.json()["detail"]) == (400, "InvalidOAuthState")
    assert await session.scalar(select(Account)) is None


@pytest.mark.parametrize("step", ["exchange_code", "long_lived_token", "get_me", "subscribe"])
async def test_meta_error(client, session, owner, monkeypatch, step):
    meta(monkeypatch, FakeMeta(fail_on=step))
    state = await start(client, owner)
    with capture_logs() as logs:
        r = await client.post(CALLBACK, headers=owner, json={"code": "abc", "state": state})
    assert (r.status_code, r.json()["detail"]) == (502, "OAuthFailed")
    # подписка не прошла: аккаунта нет, человек просто повторит
    assert await session.scalar(select(Account)) is None
    [failed] = [e for e in logs if e["event"] == "account.connect_failed"]
    assert (failed["step"], failed["code"]) == (step, 190)
    assert LEAK not in repr(logs)


async def test_connected_logged_without_token(client, owner, monkeypatch):
    meta(monkeypatch, FakeMeta())
    state = await start(client, owner)
    with capture_logs() as logs:
        await client.post(CALLBACK, headers=owner, json={"code": "abc", "state": state})
    [connected] = [e for e in logs if e["event"] == "account.connected"]
    assert connected["ig_user_id"] == connected["oauth_user_id"] == IG_USER_ID
    assert LONG_TOKEN not in repr(logs) and "short" not in repr(logs)


async def test_member_without_right(client, owner, login_as):
    member = await login_as("member")
    assert (await client.get(URL, headers=member)).status_code == 403
    r = await client.post(CALLBACK, headers=member, json={"code": "a", "state": "b"})
    assert r.status_code == 403


async def test_list_accounts(client, owner, login_as, monkeypatch):
    meta(monkeypatch, FakeMeta())
    await client.post(
        CALLBACK, headers=owner, json={"code": "a", "state": await start(client, owner)}
    )
    r = await client.get("/instagram/accounts", headers=await login_as("member"))
    assert [(a["username"], a["status"]) for a in r.json()] == [("shop", "active")]
    assert not any("token" in key for key in r.json()[0])


async def test_list_accounts_needs_login(client):
    assert (await client.get("/instagram/accounts")).status_code == 401
