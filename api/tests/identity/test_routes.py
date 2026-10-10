import pytest

from app.config import settings

TOKEN = "secret-token"
OWNER = {"token": TOKEN, "email": "owner@example.com", "password": "password1"}


@pytest.fixture(autouse=True)
def setup_token(monkeypatch):
    monkeypatch.setattr(settings, "setup_token", TOKEN)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def test_setup_logs_owner_in(client):
    r = await client.post("/setup", json=OWNER)
    assert r.status_code == 201

    me = await client.get("/auth/me", headers=bearer(r.json()["token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"
    assert me.json()["role"] == "owner"
    assert "password_hash" not in me.json()


async def test_setup_needed_until_owner_exists(client):
    assert (await client.get("/setup")).json() == {"needed": True}
    await client.post("/setup", json=OWNER)
    assert (await client.get("/setup")).json() == {"needed": False}


async def test_setup_disabled_looks_absent(client, monkeypatch):
    monkeypatch.setattr(settings, "setup_token", None)
    r = await client.post("/setup", json=OWNER)
    assert r.status_code == 404


@pytest.mark.parametrize(
    ("change", "status", "detail"),
    [
        ({"token": "wrong"}, 403, "InvalidSetupToken"),
        ({"password": "1234567"}, 422, "WeakPassword"),
    ],
)
async def test_setup_errors(client, change, status, detail):
    r = await client.post("/setup", json=OWNER | change)
    assert (r.status_code, r.json()["detail"]) == (status, detail)


async def test_setup_twice(client):
    await client.post("/setup", json=OWNER)
    r = await client.post("/setup", json=OWNER | {"email": "other@example.com"})
    assert (r.status_code, r.json()["detail"]) == (409, "OwnerAlreadyExists")


async def test_setup_rejects_bad_email(client):
    r = await client.post("/setup", json=OWNER | {"email": "not-an-email"})
    assert r.status_code == 422


async def test_login_and_logout(client):
    await client.post("/setup", json=OWNER)
    r = await client.post(
        "/auth/login", json={"email": "Owner@Example.com", "password": "password1"}
    )
    assert r.status_code == 200
    token = r.json()["token"]

    assert (await client.post("/auth/logout", headers=bearer(token))).status_code == 204
    assert (await client.get("/auth/me", headers=bearer(token))).status_code == 401


async def test_login_wrong_password(client):
    await client.post("/setup", json=OWNER)
    r = await client.post(
        "/auth/login", json={"email": "owner@example.com", "password": "nope-nope"}
    )
    assert (r.status_code, r.json()["detail"]) == (401, "InvalidCredentials")


async def test_me_without_token(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
