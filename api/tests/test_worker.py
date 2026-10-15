"""Циклы worker: одно событие за раз, каждое в своей сессии; остановка по сигналу."""

import asyncio
import signal
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select

from app import autoreplies, instagram, worker
from app.autoreplies.models import Autoreply, Keyword
from app.core import crypto
from app.instagram import tasks, webhook
from app.instagram.models import Account, InboxEvent, OutboxTask


def sessions(session):
    """Фабрика сессий для цикла: отдаёт песочницу теста и не закрывает её."""

    @asynccontextmanager
    async def make():
        yield session

    return make


async def add_events(session, count: int) -> None:
    for _ in range(count):
        session.add(
            InboxEvent(
                ig_account_id="0",
                kind=webhook.COMMENT,
                dedup_key=f"comment:{uuid.uuid4()}",
                payload={},
            )
        )
    await session.commit()


async def pending(session) -> int:
    return await session.scalar(
        select(func.count()).select_from(InboxEvent).where(InboxEvent.processed_at.is_(None))
    )


async def test_nothing_to_do(session):
    assert await worker.inbox_once(sessions(session)) is False
    assert await worker.outbox_once(sessions(session)) is False
    assert await worker.results_once(sessions(session)) is False


async def test_one_event_at_a_time(session):
    await add_events(session, 2)
    assert await worker.inbox_once(sessions(session)) is True
    assert await pending(session) == 1
    assert await worker.inbox_once(sessions(session)) is True
    assert await pending(session) == 0
    assert await worker.inbox_once(sessions(session)) is False


AUTOREPLY_ID = uuid.uuid7()


@pytest.mark.parametrize(
    ("handler", "module_fn"),
    [("on_comment", "handle_comment"), ("on_postback", "handle_postback")],
)
@pytest.mark.parametrize(
    ("taken", "handled"),
    [
        # взял: модуль и какой автоответ; в ленте его название
        (
            autoreplies.Taken(AUTOREPLY_ID),
            instagram.Handled("autoreplies", str(AUTOREPLY_ID)),
        ),
        # взял, но какой автоответ, не понять
        (autoreplies.Taken(None), instagram.Handled("autoreplies", None)),
        (None, None),
    ],
)
async def test_inbox_goes_to_autoreplies(monkeypatch, handler, module_fn, taken, handled):
    got = []

    async def fake(session, ref):
        got.append(ref)
        return taken

    monkeypatch.setattr(autoreplies, module_fn, fake)
    assert await getattr(worker.HANDLERS, handler)(None, "ref") == handled
    assert got == ["ref"]


@pytest.mark.parametrize(("text", "taken"), [("хочу гайд", "autoreplies"), ("класс", None)])
async def test_comment_through_worker_knows_who_took_it(session, text, taken):
    # вся цепочка без подмен: входящее, worker, настоящий автоответ, строка входящего
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted=crypto.encrypt("t"),
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.flush()
    autoreply = Autoreply(
        account_id=account.id,
        name="Гайд",
        scope="all",
        intro_text="Держи",
        button_text="Получить",
        reply_text="https://guide",
        created_by=uuid.uuid7(),
    )
    session.add(autoreply)
    await session.flush()
    session.add(Keyword(autoreply_id=autoreply.id, word="гайд", normalized="гайд"))
    event = InboxEvent(
        ig_account_id=account.ig_user_id,
        kind=webhook.COMMENT,
        dedup_key="comment:1",
        payload={
            "id": "180001",
            "text": text,
            "from": {"id": "500001", "username": "vasya"},
            "media": {"id": "190001"},
        },
    )
    session.add(event)
    await session.commit()

    assert await worker.inbox_once(sessions(session)) is True
    await session.refresh(event)
    ref = str(autoreply.id) if taken else None
    assert (event.outcome, event.handled_by, event.handled_ref) == ("done", taken, ref)


async def test_comment_reaches_deliveries(client, session, login_as, monkeypatch):
    # вся цепочка без подмен: вебхук во входящих, worker отвечает и отправляет директ,
    # выдача видна в «Выдачах» с ником и текстом из входящих, а её шаги в истории
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted=crypto.encrypt("t"),
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.flush()
    autoreply = Autoreply(
        account_id=account.id,
        name="Гайд",
        scope="all",
        intro_text="Держи",
        button_text="Получить",
        reply_text="https://guide",
        created_by=uuid.uuid7(),
    )
    session.add(autoreply)
    await session.flush()
    session.add(Keyword(autoreply_id=autoreply.id, word="гайд", normalized="гайд"))
    session.add(
        InboxEvent(
            ig_account_id=account.ig_user_id,
            kind=webhook.COMMENT,
            # ключ, как его пишет вебхук: по нему «Выдачи» находят ник и текст коммента
            dedup_key=webhook.dedup_key(webhook.COMMENT, "180001"),
            payload={
                "id": "180001",
                "text": "хочу гайд",
                "from": {"id": "500001", "username": "vasya"},
                "media": {"id": "190001"},
            },
        )
    )
    await session.commit()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "r1"}))
    monkeypatch.setattr(tasks, "_http", lambda: httpx.AsyncClient(transport=transport))

    assert await worker.inbox_once(sessions(session)) is True
    assert await worker.outbox_once(sessions(session)) is True

    owner = await login_as("owner")
    page = await client.get(
        "/autoreplies/deliveries", headers=owner, params={"account_id": str(account.id)}
    )
    [item] = page.json()["items"]
    assert (item["username"], item["text"], item["stage"]) == (
        "vasya",
        "хочу гайд",
        "waiting_click",
    )
    r = await client.get(
        "/autoreplies/history",
        headers=owner,
        params={"account_id": str(account.id), "comment_id": item["comment_id"]},
    )
    assert [s["step"] for s in r.json()["comments"][item["comment_id"]]] == [
        "matched",
        "dm_sent",
    ]


def test_send_results_go_to_autoreplies():
    assert worker.ON_RESULT is autoreplies.handle_send_result


async def test_outbox_once_sends(session, monkeypatch):
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted=crypto.encrypt("t"),
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.flush()
    await instagram.enqueue_comment_reply(session, account_id=account.id, comment_id="c1", text="x")
    await session.commit()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "r1"}))
    monkeypatch.setattr(tasks, "_http", lambda: httpx.AsyncClient(transport=transport))

    assert await worker.outbox_once(sessions(session)) is True
    assert await worker.outbox_once(sessions(session)) is False


async def test_results_once_repeats_lost_report(session, monkeypatch):
    # отчёт об итоге не дошёл: подборщик отдаёт его тому же обработчику
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted=crypto.encrypt("t"),
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.flush()
    await instagram.enqueue_comment_reply(
        session, account_id=account.id, comment_id="c1", text="x", ref="autoreplies:d1:comment"
    )
    await session.commit()
    task = await session.scalar(select(OutboxTask))
    task.outcome, task.finished_at = "sent", func.now() - timedelta(minutes=1)
    await session.commit()
    got = []

    async def on_result(session, result):
        got.append(result.ref)

    monkeypatch.setattr(worker, "ON_RESULT", on_result)
    assert await worker.results_once(sessions(session)) is True
    assert got == ["autoreplies:d1:comment"]
    assert await worker.results_once(sessions(session)) is False


async def test_loop_works_while_busy_and_stops(monkeypatch):
    # пока работа есть, без пауз: пауза в минуту здесь сорвала бы таймаут.
    # Сигнал пришёл во время события: выходим сразу после него
    monkeypatch.setattr(worker, "POLL_SECONDS", 60)
    stop = asyncio.Event()
    calls = []

    async def once():
        calls.append(1)
        if len(calls) == 3:
            stop.set()
        return True

    await asyncio.wait_for(worker.run_loop("test", once, stop), 1)
    assert len(calls) == 3


async def test_loop_survives_errors(monkeypatch):
    # база недоступна: цикл не падает, а пробует снова
    monkeypatch.setattr(worker, "POLL_SECONDS", 0)
    stop = asyncio.Event()
    calls = []

    async def once():
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("db down")
        stop.set()
        return True

    await asyncio.wait_for(worker.run_loop("test", once, stop), 1)
    assert len(calls) == 2


async def test_sleep_wakes_on_stop(monkeypatch):
    # пустая очередь и долгий сон, но SIGTERM будит сразу
    monkeypatch.setattr(worker, "POLL_SECONDS", 60)
    stop = asyncio.Event()

    async def idle():
        return False

    task = asyncio.create_task(worker.run_loop("test", idle, stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 1)


async def test_main_starts_every_loop(monkeypatch):
    # забытый цикл тихо не работал бы никогда: сверяем, что запущены все
    names = []

    async def loop(name, once, stop):
        names.append(name)

    async def periodic(stop):
        names.append("periodic")

    monkeypatch.setattr(worker, "run_loop", loop)
    monkeypatch.setattr(worker, "periodic_loop", periodic)
    monkeypatch.setattr(worker, "engine", SimpleNamespace(dispose=AsyncMock()))
    try:
        await worker.main()
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().remove_signal_handler(sig)
    senders = [f"outbox-{n}" for n in range(worker.SENDERS)]
    assert sorted(names) == sorted(["inbox", *senders, "results", "periodic"])
