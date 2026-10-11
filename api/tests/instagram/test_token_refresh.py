"""Обновление токенов: кому пора, тот получает новый токен на 60 дней; сбой у одного
не мешает остальным; токен в логи не попадает."""

import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func
from structlog.testing import capture_logs

from app import instagram, worker
from app.core import crypto
from app.instagram import tasks
from app.instagram.models import Account

NEW_TOKEN = "IGAAnew"
SIXTY_DAYS = 5184000


class FakeMeta:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.fail_for: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/refresh_access_token"
        assert request.url.params["grant_type"] == "ig_refresh_token"
        old = request.url.params["access_token"]
        self.asked.append(old)
        if old in self.fail_for:
            return httpx.Response(500, json={"error": {"message": "x", "code": 2}})
        return httpx.Response(
            200,
            json={
                "access_token": f"{NEW_TOKEN}-{old}",
                "token_type": "bearer",
                "expires_in": SIXTY_DAYS,
            },
        )


@pytest.fixture
def meta(monkeypatch) -> FakeMeta:
    fake = FakeMeta()
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(tasks, "_http", lambda: httpx.AsyncClient(transport=transport))
    return fake


async def make(
    session, token: str, *, left: timedelta | None, status="active", keep_token=None
) -> Account:
    now = await session.scalar(func.now().select())
    account = Account(
        ig_user_id=str(uuid.uuid4().int)[:17],
        username=token,
        token_encrypted=crypto.encrypt(token)
        if (status == "active" if keep_token is None else keep_token)
        else None,
        token_expires_at=None if left is None else now + left,
        status=status,
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()
    return account


async def token_of(session, account) -> str:
    await session.refresh(account)
    return crypto.decrypt(account.token_encrypted)


async def test_due_account_refreshed(session, meta):
    account = await make(session, "old", left=timedelta(days=40))
    assert await instagram.refresh_due_tokens(session) == 1
    assert await token_of(session, account) == f"{NEW_TOKEN}-old"
    now = await session.scalar(func.now().select())
    assert account.token_expires_at == now + timedelta(seconds=SIXTY_DAYS)


async def test_unknown_expiry_refreshed(session, meta):
    account = await make(session, "old", left=None)
    await instagram.refresh_due_tokens(session)
    assert await token_of(session, account) == f"{NEW_TOKEN}-old"


async def test_fresh_token_left_alone(session, meta):
    account = await make(session, "fresh", left=timedelta(days=55))
    assert await instagram.refresh_due_tokens(session) == 0
    assert meta.asked == []
    assert await token_of(session, account) == "fresh"


@pytest.mark.parametrize(
    ("status", "keep_token"), [("disconnected", False), ("token_expired", True)]
)
async def test_inactive_left_alone(session, meta, status, keep_token):
    # токен истёк, но ещё лежит: обновлять его бесполезно, нужен новый вход
    await make(session, "gone", left=timedelta(days=1), status=status, keep_token=keep_token)
    assert await instagram.refresh_due_tokens(session) == 0
    assert meta.asked == []


async def test_failure_does_not_stop_others(session, meta):
    broken = await make(session, "broken", left=timedelta(days=10))
    fine = await make(session, "fine", left=timedelta(days=20))
    meta.fail_for = {"broken"}
    with capture_logs() as logs:
        assert await instagram.refresh_due_tokens(session) == 1
    # сломанный остался со старым, обновим в следующий запуск
    assert await token_of(session, broken) == "broken"
    assert await token_of(session, fine) == f"{NEW_TOKEN}-fine"
    [failed] = [e for e in logs if e["event"] == "account.token_refresh_failed"]
    assert failed["reason"] == "2"


async def test_network_failure_logged(session, meta, monkeypatch):
    def down(request):
        raise httpx.ConnectError("down")

    transport = httpx.MockTransport(down)
    monkeypatch.setattr(tasks, "_http", lambda: httpx.AsyncClient(transport=transport))
    account = await make(session, "old", left=timedelta(days=10))
    with capture_logs() as logs:
        assert await instagram.refresh_due_tokens(session) == 0
    assert await token_of(session, account) == "old"
    assert [e["reason"] for e in logs if e["event"] == "account.token_refresh_failed"] == [
        "ConnectError"
    ]


async def test_tokens_not_in_logs(session, meta, real_logging, capsys):
    await make(session, "secret-old", left=timedelta(days=10))
    real_logging()
    capsys.readouterr()
    await instagram.refresh_due_tokens(session)
    out = capsys.readouterr().err
    assert "account.token_refreshed" in out
    assert "secret-old" not in out


async def test_worker_periodic_refreshes(session, meta):
    account = await make(session, "old", left=timedelta(days=10))

    @asynccontextmanager
    async def same():
        yield session

    await worker.periodic(same)
    assert await token_of(session, account) == f"{NEW_TOKEN}-old"
