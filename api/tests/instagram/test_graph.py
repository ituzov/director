"""Клиент Graph API: шлёт то, что ждёт Meta, и понимает оба формата её ошибок."""

import httpx
import pytest

from app.instagram import graph

TOKEN = "IGAAtoken"
PERMISSIONS = ["instagram_business_basic", "instagram_business_manage_comments"]
# текст ошибки Meta: в нём бывают куски запроса, наружу его не выносим
LEAK = "leaked-request-part"


def client(handler) -> httpx.AsyncClient:
    """Клиент с подменённой сетью: handler видит запрос и отвечает за Meta."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_exchange_code():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "access_token": "short",
                        "user_id": 17841400000000000,
                        "permissions": ",".join(PERMISSIONS),
                    }
                ]
            },
        )

    async with client(handler) as http:
        token = await graph.exchange_code(
            http, app_id="1", app_secret="s", redirect_uri="https://x/cb", code="abc"
        )
    request = seen["request"]
    assert (request.method, str(request.url)) == ("POST", graph.OAUTH)
    form = dict(httpx.QueryParams(request.content.decode()))
    assert form == {
        "client_id": "1",
        "client_secret": "s",
        "grant_type": "authorization_code",
        "redirect_uri": "https://x/cb",
        "code": "abc",
    }
    assert token == graph.ShortToken("short", "17841400000000000", PERMISSIONS)


async def test_long_lived_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/access_token"
        assert dict(request.url.params) == {
            "grant_type": "ig_exchange_token",
            "client_secret": "s",
            "access_token": "short",
        }
        return httpx.Response(
            200, json={"access_token": "long", "token_type": "bearer", "expires_in": 5183944}
        )

    async with client(handler) as http:
        token = await graph.long_lived_token(http, app_secret="s", short_token="short")
    assert token == graph.LongToken("long", 5183944)


async def test_get_me():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/{graph.VERSION}/me"
        assert dict(request.url.params) == {"fields": "user_id,username", "access_token": TOKEN}
        return httpx.Response(200, json={"user_id": "1784", "username": "shop", "id": "999"})

    async with client(handler) as http:
        assert await graph.get_me(http, token=TOKEN) == graph.Me("1784", "shop")


async def test_subscribe():
    def handler(request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == (
            "POST",
            f"/{graph.VERSION}/me/subscribed_apps",
        )
        assert request.url.params["subscribed_fields"] == "comments,messages"
        return httpx.Response(200, json={"success": True})

    async with client(handler) as http:
        await graph.subscribe(http, token=TOKEN, fields=["comments", "messages"])


async def test_subscribe_not_confirmed():
    async with client(lambda r: httpx.Response(200, json={"success": False})) as http:
        with pytest.raises(graph.GraphError):
            await graph.subscribe(http, token=TOKEN, fields=["comments"])


@pytest.mark.parametrize(
    ("body", "code", "type_"),
    [
        # Graph API
        (
            {"error": {"message": LEAK, "type": "OAuthException", "code": 190}},
            190,
            "OAuthException",
        ),
        # обмен кода
        (
            {"error_type": "OAuthException", "code": 400, "error_message": LEAK},
            400,
            "OAuthException",
        ),
    ],
)
async def test_errors(body, code, type_):
    async with client(lambda r: httpx.Response(400, json=body)) as http:
        with pytest.raises(graph.GraphError) as info:
            await graph.get_me(http, token=TOKEN)
    assert (info.value.status, info.value.code, info.value.type) == (400, code, type_)
    assert LEAK not in str(info.value)


async def test_not_json():
    async with client(lambda r: httpx.Response(502, text="<html>bad gateway</html>")) as http:
        with pytest.raises(graph.GraphError) as info:
            await graph.get_me(http, token=TOKEN)
    assert (info.value.status, info.value.type) == (502, "not_json")
