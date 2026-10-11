"""Отправка исходящих: что уходит в Meta, срок и лимит, временные ошибки повторяются,
окончательные нет, итог уходит тому, кто поставил, уже после коммита."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from structlog.testing import capture_logs

from app import instagram
from app.core import crypto
from app.instagram import graph, tasks
from app.instagram.models import Account, OutboxTask

TOKEN = "IGAAtoken"
IG_USER_ID = "17841400000000000"
FAR = datetime(2100, 1, 1, tzinfo=UTC)


class FakeMeta:
    """Meta в тестах: запоминает запросы и отвечает заданным."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.response = httpx.Response(200, json={"recipient_id": "p1", "message_id": "mid"})
        self.error: Exception | None = None
        # ответ на вопрос о подписке
        self.follow = httpx.Response(200, json={"is_user_follow_business": True, "id": "p1"})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error:
            raise self.error
        if request.method == "GET":
            return self.follow
        return self.response

    def sent(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]

    def fail(self, status: int, code: int | None = None) -> None:
        self.response = httpx.Response(status, json={"error": {"message": "x", "code": code}})


@pytest.fixture
def meta(monkeypatch) -> FakeMeta:
    fake = FakeMeta()
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(tasks, "_http", lambda: httpx.AsyncClient(transport=transport))
    return fake


@pytest.fixture
async def account(session) -> Account:
    account = Account(
        ig_user_id=IG_USER_ID,
        username="shop",
        token_encrypted=crypto.encrypt(TOKEN),
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()
    return account


class Results:
    def __init__(self) -> None:
        self.got: list[instagram.OutboxResult] = []

    async def __call__(self, session, result) -> None:
        self.got.append(result)


async def private_reply(session, account, **kw) -> None:
    await instagram.enqueue_private_reply(
        session,
        **{
            "account_id": account.id,
            "comment_id": "c1",
            "commented_at": FAR,
            "text": "Держи 👇",
            "button": instagram.Button(title="Получить", payload="d1"),
            "ref": "autoreplies:d1",
        }
        | kw,
    )
    await session.commit()


async def stored(session) -> OutboxTask:
    [task] = (
        await session.scalars(select(OutboxTask).execution_options(populate_existing=True))
    ).all()
    return task


async def test_nothing_to_send(session, meta):
    assert await instagram.send_outbox_task(session) is False
    assert meta.requests == []


async def test_private_reply_with_button(session, account, meta):
    await private_reply(session, account)
    results = Results()
    assert await instagram.send_outbox_task(session, results) is True

    [request] = meta.requests
    assert request.url.path == f"/{graph.VERSION}/{IG_USER_ID}/messages"
    assert request.url.params["access_token"] == TOKEN
    assert json.loads(request.content) == {
        "recipient": {"comment_id": "c1"},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "Держи 👇",
                    "buttons": [{"type": "postback", "title": "Получить", "payload": "d1"}],
                },
            }
        },
    }
    task = await stored(session)
    assert (task.outcome, task.reason, task.finished_at is not None) == ("sent", None, True)
    assert results.got == [instagram.OutboxResult("autoreplies:d1", "private_reply", "sent", None)]


async def test_message_to_person(session, account, meta):
    await instagram.enqueue_message(
        session,
        account_id=account.id,
        recipient_id="p1",
        acted_at=FAR,
        text="ссылка",
        dedup_key="click:1",
    )
    await session.commit()
    await instagram.send_outbox_task(session)
    assert json.loads(meta.requests[0].content) == {
        "recipient": {"id": "p1"},
        "message": {"text": "ссылка"},
    }


async def test_comment_reply(session, account, meta):
    await instagram.enqueue_comment_reply(
        session, account_id=account.id, comment_id="c1", text="Отправили!"
    )
    await session.commit()
    await instagram.send_outbox_task(session)
    [request] = meta.requests
    assert request.url.path == f"/{graph.VERSION}/c1/replies"
    assert json.loads(request.content) == {"message": "Отправили!"}


async def test_not_before_run_at(session, account, meta):
    await private_reply(session, account)
    task = await stored(session)
    task.run_at = FAR
    await session.commit()
    assert await instagram.send_outbox_task(session) is False


async def test_expired_not_sent(session, account, meta):
    # коммент написали 8 дней назад: Private Reply Meta уже не примет
    await private_reply(session, account, commented_at=datetime.now(UTC) - timedelta(days=8))
    results = Results()
    await instagram.send_outbox_task(session, results)
    assert meta.requests == []
    assert (await stored(session)).outcome == "expired"
    assert results.got[0].outcome == "expired"


async def test_inactive_account_not_sent(session, account, meta):
    await private_reply(session, account)
    account.status, account.token_encrypted = "disconnected", None
    await session.commit()
    results = Results()
    await instagram.send_outbox_task(session, results)
    assert meta.requests == []
    task = await stored(session)
    assert (task.outcome, task.reason) == ("failed", "account_inactive")
    assert results.got[0].reason == "account_inactive"


async def test_hour_limit_defers(session, account, meta, monkeypatch):
    monkeypatch.setattr(tasks, "PRIVATE_REPLIES_PER_HOUR", 2)
    sent_at = datetime.now(UTC) - timedelta(minutes=30)
    # отправка двухчасовой давности в лимит часа не входит
    session.add(
        OutboxTask(
            account_id=account.id,
            kind="private_reply",
            payload={},
            dedup_key="older",
            outcome="sent",
            finished_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    for n in range(2):
        session.add(
            OutboxTask(
                account_id=account.id,
                kind="private_reply",
                payload={},
                dedup_key=f"old:{n}",
                outcome="sent",
                finished_at=sent_at + timedelta(minutes=n),
            )
        )
    await private_reply(session, account)

    results = Results()
    with capture_logs() as logs:
        assert await instagram.send_outbox_task(session, results) is True
    assert meta.requests == []
    # отложено, а не завершено: итога нет и сообщать нечего
    assert results.got == []
    assert "outbox.result_failed" not in [e["event"] for e in logs]
    task = await session.scalar(select(OutboxTask).where(OutboxTask.outcome.is_(None)))
    # освободится, когда самому раннему из часа исполнится час
    assert task.run_at == sent_at + timedelta(hours=1)


async def test_hour_limit_counts_only_last_hour(session, account, meta, monkeypatch):
    monkeypatch.setattr(tasks, "PRIVATE_REPLIES_PER_HOUR", 1)
    session.add(
        OutboxTask(
            account_id=account.id,
            kind="private_reply",
            payload={},
            dedup_key="older",
            outcome="sent",
            finished_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    await private_reply(session, account)
    await instagram.send_outbox_task(session)
    assert len(meta.requests) == 1


async def test_hour_limit_only_for_private_replies(session, account, meta, monkeypatch):
    monkeypatch.setattr(tasks, "PRIVATE_REPLIES_PER_HOUR", 0)
    await instagram.enqueue_comment_reply(session, account_id=account.id, comment_id="c1", text="x")
    await session.commit()
    await instagram.send_outbox_task(session)
    assert len(meta.requests) == 1


@pytest.mark.parametrize(
    ("status", "code", "reason"),
    [(500, None, "500"), (400, 4, "4"), (400, 613, "613"), (429, None, "429")],
)
async def test_temporary_error_retried(session, account, meta, status, code, reason):
    await private_reply(session, account)
    meta.fail(status, code)
    results = Results()
    with capture_logs() as logs:
        await instagram.send_outbox_task(session, results)
    assert "outbox.result_failed" not in [e["event"] for e in logs]
    task = await stored(session)
    assert (task.outcome, task.attempts, task.reason) == (None, 1, reason)
    assert task.run_at > await session.scalar(func.now().select())
    assert results.got == []


async def test_network_error_retried(session, account, meta):
    await private_reply(session, account)
    meta.error = httpx.ReadTimeout("slow")
    await instagram.send_outbox_task(session)
    task = await stored(session)
    assert (task.outcome, task.attempts, task.reason) == (None, 1, "ReadTimeout")


async def test_final_error_not_retried(session, account, meta):
    await private_reply(session, account)
    # коммент удалили или окно закрыто: повтор не поможет
    meta.fail(400, 100)
    results = Results()
    await instagram.send_outbox_task(session, results)
    task = await stored(session)
    assert (task.outcome, task.reason, task.attempts) == ("failed", "100", 1)
    assert results.got == [
        instagram.OutboxResult("autoreplies:d1", "private_reply", "failed", "100")
    ]


async def test_fifth_temporary_error_gives_up(session, account, meta):
    await private_reply(session, account)
    task = await stored(session)
    task.attempts = 4
    await session.commit()
    meta.fail(500)
    results = Results()
    await instagram.send_outbox_task(session, results)
    task = await stored(session)
    # сдались по ошибке Meta, а не из-за сбоя в нашем коде
    assert (task.outcome, task.reason, task.attempts) == ("failed", "500", 5)
    assert results.got[0].outcome == "failed"


async def test_result_handler_failure_keeps_sent(session, account, meta):
    await private_reply(session, account)

    async def broken(session, result):
        raise RuntimeError("boom")

    with capture_logs() as logs:
        await instagram.send_outbox_task(session, broken)
    # письмо ушло и отмечено: второй раз не уйдёт, даже если итог не записался
    assert (await stored(session)).outcome == "sent"
    assert "outbox.result_failed" in [e["event"] for e in logs]
    assert await instagram.send_outbox_task(session) is False


async def test_without_ref_no_result(session, account, meta):
    await instagram.enqueue_comment_reply(session, account_id=account.id, comment_id="c1", text="x")
    await session.commit()
    results = Results()
    await instagram.send_outbox_task(session, results)
    assert results.got == []


async def test_token_not_in_logs(session, account, meta, real_logging, capsys):
    await private_reply(session, account)
    real_logging()
    capsys.readouterr()
    await instagram.send_outbox_task(session)
    out = capsys.readouterr().err
    assert "outbox.sent" in out
    assert TOKEN not in out


async def gated(session, account, **kw) -> None:
    await instagram.enqueue_message(
        session,
        **{
            "account_id": account.id,
            "recipient_id": "p1",
            "acted_at": FAR,
            "text": "ссылка на гайд",
            "dedup_key": "d1:0",
            "ref": "autoreplies:d1:material",
            "if_not_following": (
                "Подпишись 🙂",
                instagram.Button(title="Получить", payload="ar:d1"),
            ),
        }
        | kw,
    )
    await session.commit()


async def test_following_gets_main(session, account, meta):
    await gated(session, account)
    results = Results()
    await instagram.send_outbox_task(session, results)
    check = meta.requests[0]
    assert (check.method, check.url.path) == ("GET", f"/{graph.VERSION}/p1")
    assert check.url.params["fields"] == "is_user_follow_business"
    assert meta.sent() == [{"recipient": {"id": "p1"}, "message": {"text": "ссылка на гайд"}}]
    assert results.got[0].variant == "following"


async def test_not_following_gets_other(session, account, meta):
    meta.follow = httpx.Response(200, json={"is_user_follow_business": False, "id": "p1"})
    await gated(session, account)
    results = Results()
    await instagram.send_outbox_task(session, results)
    [body] = meta.sent()
    assert body["message"]["attachment"]["payload"]["text"] == "Подпишись 🙂"
    assert body["message"]["attachment"]["payload"]["buttons"][0]["payload"] == "ar:d1"
    assert (results.got[0].outcome, results.got[0].variant) == ("sent", "not_following")


@pytest.mark.parametrize(
    ("if_unknown", "text"),
    [("following", "ссылка на гайд"), ("not_following", None)],
)
async def test_no_consent_uses_callers_choice(session, account, meta, if_unknown, text):
    # Meta не дала проверить: человек не давал согласия
    meta.follow = httpx.Response(400, json={"error": {"message": "x", "code": 230}})
    await gated(session, account, if_unknown=if_unknown)
    results = Results()
    with capture_logs() as logs:
        await instagram.send_outbox_task(session, results)
    [body] = meta.sent()
    if text:
        assert body["message"] == {"text": text}
    else:
        assert body["message"]["attachment"]["payload"]["text"] == "Подпишись 🙂"
    assert results.got[0].variant == "unknown"
    assert "outbox.follow_unknown" in [e["event"] for e in logs]


async def test_follow_check_down_retried(session, account, meta):
    meta.follow = httpx.Response(500, json={"error": {"message": "x", "code": 2}})
    await gated(session, account)
    results = Results()
    await instagram.send_outbox_task(session, results)
    # проверка не прошла: ничего не отправили, повторим позже
    assert meta.sent() == []
    task = await stored(session)
    assert (task.outcome, task.attempts) == (None, 1)
    assert results.got == []


async def test_plain_message_not_checked(session, account, meta):
    await instagram.enqueue_message(
        session,
        account_id=account.id,
        recipient_id="p1",
        acted_at=FAR,
        text="ссылка",
        dedup_key="k",
        ref="autoreplies:d1:material",
    )
    await session.commit()
    results = Results()
    await instagram.send_outbox_task(session, results)
    assert [r.method for r in meta.requests] == ["POST"]
    assert results.got[0].variant is None
