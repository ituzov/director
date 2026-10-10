"""Зависимости для соседей: справка вместо модели и доступ только владельцу.

Соседский модуль тут изображает отдельное приложение с ручками под этими
зависимостями: так проверяем ровно то, что видят соседи через __init__.
"""

import dataclasses
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.identity import (
    CurrentOwner,
    CurrentUserRef,
    IdentityError,
    UserRef,
    identity_error_handler,
    repository,
    service,
)
from app.identity.passwords import hash_password

neighbour = FastAPI(exception_handlers={IdentityError: identity_error_handler})


@neighbour.get("/whoami")
async def whoami(user: CurrentUserRef) -> dict:
    return {"type": type(user).__name__, "role": user.role}


@neighbour.get("/owner-only")
async def owner_only(owner: CurrentOwner) -> dict:
    return {"role": owner.role}


@pytest.fixture
async def probe(session):
    neighbour.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=neighbour), base_url="http://test") as c:
        yield c
    neighbour.dependency_overrides.clear()


async def login_as(session, role: str) -> dict:
    email = f"{role}@test.dev"
    repository.add_user(session, email=email, password_hash=hash_password("password1"), role=role)
    await session.commit()
    token = await service.login(session, email=email, password="password1")
    return {"Authorization": f"Bearer {token}"}


async def test_neighbour_gets_ref(probe, session):
    r = await probe.get("/whoami", headers=await login_as(session, "member"))
    assert r.json() == {"type": "UserRef", "role": "member"}


async def test_owner_passes(probe, session):
    r = await probe.get("/owner-only", headers=await login_as(session, "owner"))
    assert (r.status_code, r.json()) == (200, {"role": "owner"})


async def test_member_rejected(probe, session):
    r = await probe.get("/owner-only", headers=await login_as(session, "member"))
    assert (r.status_code, r.json()["detail"]) == (403, "OwnerOnly")


async def test_no_token(probe):
    assert (await probe.get("/owner-only")).status_code == 401


def test_ref_is_read_only():
    ref = UserRef(id=uuid.uuid7(), role="member", can_connect_accounts=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.role = "owner"
