"""Ручки ассистентов: места как у автоответов (общий один, пост у одного
частного, пауза держит, архив отпускает), модель сохраняется вместе с формой,
смотрят все, правит владелец."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.ai.models import Binding, Connection
from app.assistant.models import Assistant, Reply
from app.core import crypto
from app.instagram.models import Account


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


@pytest.fixture
async def account(session) -> Account:
    account = Account(
        ig_user_id="17841400000000000",
        username="altai.tours",
        token_encrypted="x",
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()
    return account


@pytest.fixture
async def connection(session) -> Connection:
    connection = Connection(
        provider="timeweb",
        name="Таймвеб",
        key_encrypted=crypto.encrypt("sk-test-key-0123456789"),
        key_hint="6789",
        key_changed_at=datetime.now(UTC),
        created_by=uuid.uuid7(),
    )
    session.add(connection)
    await session.commit()
    return connection


def form(account, connection, **kw) -> dict:
    return {
        "account_id": str(account.id),
        "name": "Все вопросы",
        "scope": "all",
        "mode": "direct",
        "instruction": "Пиши на «вы».",
        "knowledge": "С собакой: на Алтай нельзя.",
        "daily_limit": 200,
        "connection_id": str(connection.id),
        "model": "anthropic/claude-haiku-5-5",
    } | kw


async def create(client, headers, body):
    return await client.post("/assistants", headers=headers, json=body)


def without_account(body: dict) -> dict:
    return {k: v for k, v in body.items() if k != "account_id"}


async def count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_create_and_read(client, owner, account, connection, session):
    r = await create(client, owner, form(account, connection))
    assert r.status_code == 201
    body = r.json()
    assert (body["scope"], body["media_ids"], body["enabled"]) == ("all", [], True)
    # модель сохранилась в ai вместе с формой
    assert (body["connection_id"], body["model"]) == (
        str(connection.id),
        "anthropic/claude-haiku-5-5",
    )
    assert body["model_missing"] is False
    assert body["today"] == {"answered": 0, "unsure": 0, "not_mine": 0}
    assert (await client.get(f"/assistants/{body['id']}", headers=owner)).json() == body
    listed = await client.get("/assistants", headers=owner, params={"account_id": str(account.id)})
    assert listed.json() == [body]
    [binding] = list(await session.scalars(select(Binding)))
    assert (binding.purpose, binding.scope) == ("assistant.answer", body["id"])


async def test_one_general_per_account(client, owner, account, connection):
    first = (await create(client, owner, form(account, connection))).json()
    r = await create(client, owner, form(account, connection, name="Второй"))
    assert r.status_code == 409
    assert r.json() == {
        "detail": "AssistantConflict",
        "conflict": {
            "kind": "general",
            "value": None,
            "assistant": {"id": first["id"], "name": "Все вопросы", "enabled": True},
        },
    }


async def test_paused_holds_archived_releases(client, owner, account, connection):
    first = (await create(client, owner, form(account, connection))).json()
    url = f"/assistants/{first['id']}"
    # пауза держит место: на паузе тоже конфликт
    await client.put(f"{url}/enabled", headers=owner, json={"enabled": False})
    r = await create(client, owner, form(account, connection, name="Второй"))
    assert (r.status_code, r.json()["conflict"]["assistant"]["enabled"]) == (409, False)
    # архив отпускает: второй встаёт, а первый из архива уже не вернуть
    await client.post(f"{url}/archive", headers=owner)
    assert (
        await create(client, owner, form(account, connection, name="Второй"))
    ).status_code == 201
    r = await client.post(f"{url}/unarchive", headers=owner)
    assert (r.status_code, r.json()["conflict"]["kind"]) == (409, "general")


async def test_post_has_one_assistant(client, owner, account, connection):
    posts = form(account, connection, scope="posts", media_ids=["m2", "m1", "m1"], name="Алтай")
    first = (await create(client, owner, posts)).json()
    # повторы схлопнуты, порядок по id
    assert first["media_ids"] == ["m1", "m2"]
    r = await create(
        client, owner, form(account, connection, scope="posts", media_ids=["m3", "m2"])
    )
    assert r.status_code == 409
    assert (r.json()["conflict"]["kind"], r.json()["conflict"]["value"]) == ("post", "m2")
    await client.post(f"/assistants/{first['id']}/archive", headers=owner)
    again = form(account, connection, scope="posts", media_ids=["m3", "m2"])
    assert (await create(client, owner, again)).status_code == 201


async def test_general_and_private_together(client, owner, account, connection):
    # общий и частный не мешают друг другу: частный забирает свои посты
    await create(client, owner, form(account, connection))
    posts = form(account, connection, scope="posts", media_ids=["m1"], name="Алтай")
    assert (await create(client, owner, posts)).status_code == 201


@pytest.mark.parametrize(
    "kw",
    [
        {"scope": "all", "media_ids": ["m1"]},
        {"scope": "posts", "media_ids": []},
        {"knowledge": "x" * 50_001},
        {"daily_limit": 0},
        {"mode": "dm"},
        {"model": "  "},
    ],
    ids=["general-with-posts", "private-without-posts", "knowledge", "limit", "mode", "model"],
)
async def test_form_errors(client, owner, account, connection, session, kw):
    r = await create(client, owner, form(account, connection, **kw))
    assert r.status_code == 422
    assert await count(session, Assistant) == 0


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"scope": "all", "media_ids": ["m1"]}, "posts_not_allowed"),
        ({"scope": "posts", "media_ids": []}, "posts_required"),
    ],
)
async def test_scope_error_codes(client, owner, account, connection, kw, code):
    # по коду web выбирает текст у поля «Где работает»
    r = await create(client, owner, form(account, connection, **kw))
    assert code in r.json()["detail"][0]["msg"]


async def test_connection_gone(client, owner, account, connection, session):
    # подключение удалили в другой вкладке: ошибка поля, и не сохранилось ничего
    r = await create(client, owner, form(account, connection, connection_id=str(uuid.uuid7())))
    assert (r.status_code, r.json()) == (422, {"detail": "ConnectionMissing"})
    # в жизни сессия запроса на ошибке откатывается (get_session), здесь она общая
    await session.rollback()
    assert (await count(session, Assistant), await count(session, Binding)) == (0, 0)


async def test_account_unavailable(client, owner, account, connection, session):
    account.status = "disconnected"
    await session.commit()
    r = await create(client, owner, form(account, connection))
    assert (r.status_code, r.json()) == (409, {"detail": "AccountUnavailable"})


async def test_update_replaces(client, owner, account, connection, session):
    posts = form(account, connection, scope="posts", media_ids=["m1", "m2"], name="Алтай")
    first = (await create(client, owner, posts)).json()
    url = f"/assistants/{first['id']}"
    body = without_account(posts) | {"media_ids": ["m3"], "mode": "combo", "model": "sonnet"}
    r = await client.put(url, headers=owner, json=body)
    assert (r.json()["media_ids"], r.json()["mode"], r.json()["model"]) == (
        ["m3"],
        "combo",
        "sonnet",
    )
    # m1 отпущен: другой частный его берёт
    other = form(account, connection, scope="posts", media_ids=["m1"], name="Карелия")
    assert (await create(client, owner, other)).status_code == 201
    # одна настройка модели на ассистента, а не новая на каждое сохранение
    assert await count(session, Binding) == 2


async def test_archived_not_edited(client, owner, account, connection):
    first = (await create(client, owner, form(account, connection))).json()
    url = f"/assistants/{first['id']}"
    await client.post(f"{url}/archive", headers=owner)
    body = without_account(form(account, connection))
    assert (await client.put(url, headers=owner, json=body)).json() == {
        "detail": "AssistantArchived"
    }
    r = await client.put(f"{url}/enabled", headers=owner, json={"enabled": True})
    assert r.status_code == 409


async def test_today_counts(client, owner, account, connection, session):
    first = (await create(client, owner, form(account, connection))).json()
    now = datetime.now(UTC)
    yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=1)

    def reply(n, outcome, taken_at):
        return Reply(
            assistant_id=uuid.UUID(first["id"]),
            account_id=account.id,
            comment_id=f"c{n}",
            media_id="m1",
            person_id="p1",
            comment_text="?",
            commented_at=taken_at,
            stage="done",
            outcome=outcome,
            taken_at=taken_at,
        )

    session.add_all(
        [
            reply(1, "answered", now),
            reply(2, "answered", now),
            reply(3, "unsure", now),
            reply(4, "not_mine", now),
            # вчера по UTC: в «сегодня» не входит
            reply(5, "answered", yesterday),
        ]
    )
    await session.commit()
    body = (await client.get(f"/assistants/{first['id']}", headers=owner)).json()
    assert body["today"] == {"answered": 2, "unsure": 1, "not_mine": 1}


async def test_model_missing_and_connection_deleted(client, owner, account, connection, session):
    first = (await create(client, owner, form(account, connection))).json()
    binding = await session.scalar(select(Binding))
    binding.model_missing_at = datetime.now(UTC)
    await session.commit()
    url = f"/assistants/{first['id']}"
    assert (await client.get(url, headers=owner)).json()["model_missing"] is True
    await session.delete(connection)
    await session.commit()
    # ссылку обнулила база (ON DELETE SET NULL): новый запрос видит её свежей
    session.expire_all()
    # подключение удалили: ассистент «не настроен», а не пропал
    assert (await client.get(url, headers=owner)).json()["connection_id"] is None


async def test_not_found(client, owner):
    r = await client.get(f"/assistants/{uuid.uuid7()}", headers=owner)
    assert (r.status_code, r.json()) == (404, {"detail": "AssistantNotFound"})


WRITES = [
    ("POST", "", "create"),
    ("PUT", "/{id}", "update"),
    ("PUT", "/{id}/enabled", "enabled"),
    ("POST", "/{id}/archive", None),
    ("POST", "/{id}/unarchive", None),
]


@pytest.mark.parametrize("granted", [False, True], ids=["member", "can_connect"])
@pytest.mark.parametrize(("method", "path", "kind"), WRITES)
async def test_only_owner_changes(
    client, owner, login_as, account, connection, session, method, path, kind, granted
):
    # ассистент тратит ключ владельца: менять только ему, смотреть всем
    first = (await create(client, owner, form(account, connection))).json()
    member = await login_as("member")
    if granted:
        from app.identity import repository as identity_repository

        user = await identity_repository.user_by_email(session, "member@test.dev")
        user.can_connect_accounts = True
        await session.commit()
    params = {"account_id": str(account.id)}
    assert (await client.get("/assistants", headers=member, params=params)).status_code == 200
    assert (await client.get(f"/assistants/{first['id']}", headers=member)).status_code == 200
    body = {
        "create": form(account, connection, scope="posts", media_ids=["m1"]),
        "update": without_account(form(account, connection, name="Чужое")),
        "enabled": {"enabled": False},
    }.get(kind)
    url = "/assistants" + path.format(id=first["id"])
    r = await client.request(method, url, headers=member, json=body)
    assert r.status_code == 403
    after = (await client.get(f"/assistants/{first['id']}", headers=owner)).json()
    assert (after["name"], after["enabled"], after["archived_at"]) == ("Все вопросы", True, None)
    assert await count(session, Assistant) == 1


async def test_update_conflicts(client, owner, account, connection):
    # правка в чужой пост или во второго общего: понятный 409, а не 500 от индекса
    await create(client, owner, form(account, connection))
    altai = form(account, connection, scope="posts", media_ids=["m1"], name="Алтай")
    await create(client, owner, altai)
    karelia = (
        await create(
            client,
            owner,
            form(account, connection, scope="posts", media_ids=["m2"], name="Карелия"),
        )
    ).json()
    url = f"/assistants/{karelia['id']}"
    body = without_account(
        form(account, connection, scope="posts", media_ids=["m1"], name="Карелия")
    )
    r = await client.put(url, headers=owner, json=body)
    assert (r.status_code, r.json()["conflict"]["kind"]) == (409, "post")
    r = await client.put(url, headers=owner, json=without_account(form(account, connection)))
    assert (r.status_code, r.json()["conflict"]["kind"]) == (409, "general")


@pytest.mark.parametrize("path", ["", "/{id}"])
async def test_anonymous(client, owner, account, connection, path):
    first = (await create(client, owner, form(account, connection))).json()
    url = "/assistants" + path.format(id=first["id"])
    r = await client.get(url, params={"account_id": str(account.id)})
    assert r.status_code == 401
