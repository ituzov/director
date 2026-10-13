"""GET /updates: только владелец, ответ целиком, сайт недоступен без 5xx."""

import httpx
import pytest

from app.config import settings
from app.updates import feed, routes

URL = "/updates"

BODY = {
    "schema": 1,
    "channels": {"stable": "0.1.1", "rc": None},
    "versions": [
        {
            "version": "0.1.1",
            "date": "2026-10-20",
            "notes": {"ru": "Исправления", "en": "Fixes"},
            "important": {"ru": "Сделайте бэкап", "en": "Back up first"},
            "breaking": False,
            "security": True,
            "min_from": None,
        }
    ],
    "message": None,
}


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    feed.reset_cache()
    monkeypatch.setattr(settings, "app_version", "0.1.0")
    monkeypatch.setattr(settings, "director_channel", "stable")
    yield
    feed.reset_cache()


def site(monkeypatch, answer: httpx.Response) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return answer

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(routes, "_http", lambda: httpx.AsyncClient(transport=transport))
    return calls


async def test_owner_sees_available(client, login_as, monkeypatch):
    calls = site(monkeypatch, httpx.Response(200, json=BODY))
    r = await client.get(URL, headers=await login_as("owner"))
    assert r.status_code == 200
    assert str(calls[0].url) == settings.updates_url
    assert r.json() == {
        "current": "0.1.0",
        "channel": "stable",
        "available": {
            "latest": "0.1.1",
            "releases": [
                {
                    "version": "0.1.1",
                    "date": "2026-10-20",
                    "notes": {"ru": "Исправления", "en": "Fixes"},
                    "important": {"ru": "Сделайте бэкап", "en": "Back up first"},
                    "breaking": False,
                    "security": True,
                }
            ],
            "blocked": None,
            "min_from": None,
        },
        "message": None,
        "error": None,
    }


async def test_site_down_is_not_an_error_page(client, login_as, monkeypatch):
    site(monkeypatch, httpx.Response(502))
    r = await client.get(URL, headers=await login_as("owner"))
    assert r.status_code == 200
    assert (r.json()["error"], r.json()["available"]) == ("unreachable", None)


async def test_member_forbidden(client, login_as, monkeypatch):
    calls = site(monkeypatch, httpx.Response(200, json=BODY))
    r = await client.get(URL, headers=await login_as("member"))
    assert r.status_code == 403
    # участнику даже не ходим на сайт
    assert calls == []


async def test_anonymous(client, monkeypatch):
    site(monkeypatch, httpx.Response(200, json=BODY))
    r = await client.get(URL)
    assert r.status_code == 401
