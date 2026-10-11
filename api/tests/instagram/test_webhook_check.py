"""Самопроверка адреса вебхука из админки: понятная причина, если Meta до нас не дойдёт."""

import ssl

import httpx
import pytest

from app.config import settings
from app.instagram import repository, service
from app.main import app

URL = "/instagram/app/webhook-check"


@pytest.fixture
async def owner(login_as, session):
    headers = await login_as("owner")
    await service.save_meta_app(session, app_id="1", app_secret="a" * 32)
    return headers


@pytest.fixture(autouse=True)
def public_url(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "http://test")


def network(monkeypatch, handler) -> None:
    """Подменить сеть самопроверки: handler получает запрос и отвечает или бросает."""
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(service, "_http", lambda: httpx.AsyncClient(transport=transport))


def fails_with(exc: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


async def test_passes_through_real_handler(client, session, owner, monkeypatch):
    # запрос уходит в наше же приложение: проверяется настоящая ручка вебхука
    monkeypatch.setattr(
        service,
        "_http",
        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    r = await client.post(URL, headers=owner)
    assert r.json() == {"ok": True, "error": None}
    # самопроверка не выдаёт себя за Meta
    assert (await repository.get_meta_app(session)).webhook_verified_at is None


async def test_no_public_url(client, owner, monkeypatch):
    monkeypatch.setattr(settings, "public_url", None)
    r = await client.post(URL, headers=owner)
    assert r.json() == {"ok": False, "error": "no_public_url"}


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (fails_with(httpx.ReadTimeout("slow")), "timeout"),
        (fails_with(httpx.ConnectError("refused")), "unreachable"),
        (lambda r: httpx.Response(404), "bad_status"),
        (lambda r: httpx.Response(200, text="<html>"), "bad_body"),
    ],
)
async def test_errors(client, owner, monkeypatch, handler, error):
    network(monkeypatch, handler)
    r = await client.post(URL, headers=owner)
    assert r.json() == {"ok": False, "error": error}


async def test_tls(client, owner, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        try:
            raise ssl.SSLCertVerificationError("certificate verify failed")
        except ssl.SSLError as exc:
            raise httpx.ConnectError("tls") from exc

    network(monkeypatch, handler)
    r = await client.post(URL, headers=owner)
    assert r.json() == {"ok": False, "error": "tls"}


async def test_owner_only(client, login_as):
    r = await client.post(URL, headers=await login_as("member"))
    assert r.status_code == 403
