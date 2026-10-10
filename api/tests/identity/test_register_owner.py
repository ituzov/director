import pytest

from app.config import settings
from app.identity import repository, service
from app.identity.exceptions import (
    InvalidSetupToken,
    OwnerAlreadyExists,
    SetupDisabled,
    WeakPassword,
)
from app.identity.passwords import verify_password

TOKEN = "secret-token"


@pytest.fixture(autouse=True)
def setup_token(monkeypatch):
    monkeypatch.setattr(settings, "setup_token", TOKEN)


async def register(session, *, token=TOKEN, email="owner@example.com", password="password1"):
    return await service.register_owner(session, token=token, email=email, password=password)


async def test_registers_owner(session):
    user = await register(session, email="  Owner@Example.COM ", password="password1")

    assert user.role == "owner"
    assert user.email == "owner@example.com"
    assert verify_password(user.password_hash, "password1")


async def test_setup_disabled_without_token(session, monkeypatch):
    monkeypatch.setattr(settings, "setup_token", None)
    with pytest.raises(SetupDisabled):
        await register(session)


async def test_wrong_token(session):
    with pytest.raises(InvalidSetupToken):
        await register(session, token="wrong")


async def test_non_ascii_token_is_just_wrong(session):
    with pytest.raises(InvalidSetupToken):
        await register(session, token="токен")


async def test_second_owner_rejected(session):
    await register(session)
    with pytest.raises(OwnerAlreadyExists):
        await register(session, email="other@example.com")


async def test_short_password_rejected(session):
    with pytest.raises(WeakPassword):
        await register(session, password="1234567")


async def test_race_caught_by_index(session, monkeypatch):
    """Два setup одновременно: проверку прошли оба, второго ловит one_owner."""
    await register(session)

    async def no_owner(_session):
        return False

    monkeypatch.setattr(repository, "owner_exists", no_owner)
    with pytest.raises(OwnerAlreadyExists):
        await register(session, email="other@example.com")
