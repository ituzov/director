"""Просьба обновиться и её ход: лоток request/, доска run/, ручки POST и status."""

import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import settings
from app.updates import feed, host, routes, service

BODY = {
    "schema": 1,
    "channels": {"stable": "0.1.2", "rc": None},
    "versions": [
        {
            "version": v,
            "date": "2026-10-20",
            "notes": {"ru": v, "en": v},
            "important": None,
            "breaking": False,
            "security": False,
            "min_from": None,
        }
        for v in ("0.1.1", "0.1.2")
    ],
    "message": None,
}


@pytest.fixture(autouse=True)
def installed(monkeypatch, tmp_path):
    """Установка 0.1.0 с папками обмена во временной папке и сайтом-заглушкой."""
    feed.reset_cache()
    request_dir, run_dir = tmp_path / "request", tmp_path / "run"
    request_dir.mkdir()
    run_dir.mkdir()
    monkeypatch.setattr(settings, "app_version", "0.1.0")
    monkeypatch.setattr(settings, "director_channel", "stable")
    monkeypatch.setattr(settings, "updates_request_dir", request_dir)
    monkeypatch.setattr(settings, "updates_run_dir", run_dir)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=BODY))
    monkeypatch.setattr(routes, "_http", lambda: httpx.AsyncClient(transport=transport))
    yield request_dir, run_dir
    feed.reset_cache()


def board(run_dir, text: str, log: str | None = None) -> None:
    (run_dir / host.BOARD).write_text(f"2026-10-13T11:06:39Z {text}\n")
    if log is not None:
        (run_dir / host.LOG).write_text(log)


# --- ход обновления ----------------------------------------------------------------


def test_idle_without_board():
    assert service.status(datetime.now(UTC)).phase == "idle"


@pytest.mark.parametrize(
    ("text", "phase"),
    [
        ("requested 0.1.2", "running"),
        ("pull 0.1.2", "running"),
        ("switch 0.1.0 -> 0.1.2", "running"),
        ("done 0.1.0 -> 0.1.2", "done"),
        ("done 0.1.2: installed", "done"),
        ("failed 0.1.2, rolled back to 0.1.0", "failed"),
        ("error: cannot download install.sh of 0.1.2", "failed"),
    ],
)
def test_board_phases(installed, text, phase):
    _, run_dir = installed
    board(run_dir, text)
    result = service.status(datetime.now(UTC))
    assert (result.phase, result.step) == (phase, text)
    assert result.at == datetime(2026, 10, 13, 11, 6, 39, tzinfo=UTC)


def test_log_tail_only_on_failure(installed):
    _, run_dir = installed
    log = "\n".join(f"line {i}" for i in range(100))
    board(run_dir, "pull 0.1.2", log)
    assert service.status(datetime.now(UTC)).log == ()
    board(run_dir, "failed 0.1.2, rolled back to 0.1.0", log)
    tail = service.status(datetime.now(UTC)).log
    assert len(tail) == service.LOG_TAIL
    assert tail[-1] == "line 99"


def test_broken_board_is_idle(installed):
    _, run_dir = installed
    (run_dir / host.BOARD).write_text("мусор\n")
    assert service.status(datetime.now(UTC)).phase == "idle"


def test_board_without_step_is_idle(installed):
    _, run_dir = installed
    (run_dir / host.BOARD).write_text("2026-10-13T11:06:39Z \n")
    assert service.status(datetime.now(UTC)).phase == "idle"


def test_waiting_request_queued_then_stuck(installed):
    request_dir, run_dir = installed
    # доска от прошлого обновления не должна перебивать новую просьбу
    board(run_dir, "done 0.0.9 -> 0.1.0")
    (request_dir / host.REQUEST).write_text("0.1.2\n")
    now = datetime.now(UTC)
    assert service.status(now).phase == "queued"
    assert service.status(now + service.STUCK_AFTER + timedelta(seconds=1)).phase == "stuck"


# --- просьба -----------------------------------------------------------------------


async def test_owner_requests_latest(client, login_as, installed):
    request_dir, _ = installed
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("owner"))
    assert r.status_code == 202
    assert r.json()["phase"] == "queued"
    assert (request_dir / host.REQUEST).read_text() == "0.1.2\n"
    # временный файл переименован, а не оставлен рядом
    assert sorted(os.listdir(request_dir)) == [host.REQUEST]


@pytest.mark.parametrize("version", ["0.1.1", "0.1.0", "9.9.9", "../../etc/passwd"])
async def test_only_latest_version(client, login_as, installed, version):
    request_dir, _ = installed
    r = await client.post("/updates", json={"version": version}, headers=await login_as("owner"))
    assert (r.status_code, r.json()) == (409, {"detail": "NotAvailable"})
    assert os.listdir(request_dir) == []


async def test_blocked_dev_build(client, login_as, installed, monkeypatch):
    monkeypatch.setattr(settings, "app_version", "dev")
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("owner"))
    assert (r.status_code, r.json()) == (409, {"detail": "NotAvailable"})


async def test_blocked_by_min_from(client, login_as, installed, monkeypatch):
    # последняя версия та самая, но с 0.1.0 на неё напрямую нельзя
    body = {**BODY, "versions": [{**v, "min_from": "0.1.1"} for v in BODY["versions"]]}
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    monkeypatch.setattr(routes, "_http", lambda: httpx.AsyncClient(transport=transport))
    request_dir, _ = installed
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("owner"))
    assert (r.status_code, r.json()) == (409, {"detail": "NotAvailable"})
    assert os.listdir(request_dir) == []


async def test_site_down(client, login_as, installed, monkeypatch):
    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    monkeypatch.setattr(routes, "_http", lambda: httpx.AsyncClient(transport=transport))
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("owner"))
    assert (r.status_code, r.json()) == (409, {"detail": "NotAvailable"})


@pytest.mark.parametrize("busy", ["request", "running"])
async def test_busy(client, login_as, installed, busy):
    request_dir, run_dir = installed
    if busy == "request":
        (request_dir / host.REQUEST).write_text("0.1.2\n")
    else:
        board(run_dir, "backup 0.1.0")
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("owner"))
    assert (r.status_code, r.json()) == (409, {"detail": "Busy"})


async def test_after_previous_update_finished(client, login_as, installed):
    _, run_dir = installed
    board(run_dir, "failed 0.1.1, rolled back to 0.1.0")
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("owner"))
    assert r.status_code == 202


async def test_not_installed(client, login_as, installed, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "updates_request_dir", tmp_path / "nowhere")
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("owner"))
    assert (r.status_code, r.json()) == (409, {"detail": "NotInstalled"})


async def test_dev_without_folders_is_not_installed(client, login_as, monkeypatch, tmp_path):
    # в разработке нет ни версии, ни лотка: отвечаем «только на сервере», а не «нет версии»
    monkeypatch.setattr(settings, "app_version", "dev")
    monkeypatch.setattr(settings, "updates_request_dir", tmp_path / "nowhere")
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("owner"))
    assert (r.status_code, r.json()) == (409, {"detail": "NotInstalled"})


# --- доступ ------------------------------------------------------------------------


async def test_member_cannot_request(client, login_as, installed):
    request_dir, _ = installed
    r = await client.post("/updates", json={"version": "0.1.2"}, headers=await login_as("member"))
    assert r.status_code == 403
    assert os.listdir(request_dir) == []


async def test_status_owner_only(client, login_as):
    assert (await client.get("/updates/status")).status_code == 401
    r = await client.get("/updates/status", headers=await login_as("member"))
    assert r.status_code == 403


async def test_status_route(client, login_as, installed):
    _, run_dir = installed
    board(run_dir, "pull 0.1.2")
    r = await client.get("/updates/status", headers=await login_as("owner"))
    assert r.json() == {
        "phase": "running",
        "step": "pull 0.1.2",
        "at": "2026-10-13T11:06:39Z",
        "log": [],
    }
