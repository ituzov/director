"""Правка, пауза и архив: архивный отпускает слова и посты, вернуть можно,
только если их никто не занял."""

import uuid

import pytest
from sqlalchemy import select
from structlog.testing import capture_logs

from app.autoreplies.models import Autoreply, AutoreplyMedia
from app.instagram.models import Account


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


@pytest.fixture
async def account(session) -> Account:
    account = Account(
        ig_user_id="17841400000000000",
        username="shop",
        token_encrypted="x",
        connected_by=uuid.uuid7(),
    )
    session.add(account)
    await session.commit()
    return account


def form(**kw) -> dict:
    return {
        "name": "Гайд",
        "scope": "all",
        "keywords": ["гайд"],
        "intro_text": "Держи 👇",
        "button_text": "Получить",
        "reply_text": "ссылка",
    } | kw


@pytest.fixture
def create(client, owner, account):
    async def create(**kw) -> dict:
        r = await client.post(
            "/autoreplies", headers=owner, json=form(**kw) | {"account_id": str(account.id)}
        )
        assert r.status_code == 201, r.json()
        return r.json()

    return create


async def test_update_replaces_form(client, owner, create):
    created = await create(comment_replies=["Отправили!"])
    r = await client.put(
        f"/autoreplies/{created['id']}",
        headers=owner,
        json=form(name="Новый", scope="posts", media_ids=["m1"], keywords=["прайс", "цена"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["name"], body["scope"], body["media_ids"], body["keywords"]) == (
        "Новый",
        "posts",
        ["m1"],
        ["прайс", "цена"],
    )
    # ответы в комментах в форме не прислали: стали пустыми, форма целиком
    assert body["comment_replies"] == []
    assert body["created_at"] == created["created_at"]


async def test_update_forgets_last_comment_reply(client, owner, create, session):
    created = await create(comment_replies=["a", "b"])
    autoreply = await session.get(Autoreply, uuid.UUID(created["id"]))
    autoreply.last_comment_reply = 1
    await session.commit()
    await client.put(
        f"/autoreplies/{created['id']}", headers=owner, json=form(comment_replies=["b"])
    )
    await session.refresh(autoreply)
    assert autoreply.last_comment_reply is None


async def test_update_keeps_own_words_and_posts(client, owner, create):
    created = await create(scope="posts", media_ids=["m1"])
    # сохранить то же самое: сам с собой не конфликтует
    r = await client.put(
        f"/autoreplies/{created['id']}", headers=owner, json=form(scope="posts", media_ids=["m1"])
    )
    assert r.status_code == 200


async def test_update_conflicts_with_others(client, owner, create):
    await create()
    other = await create(name="Прайс", keywords=["прайс"])
    r = await client.put(f"/autoreplies/{other['id']}", headers=owner, json=form(keywords=["гайд"]))
    assert (r.status_code, r.json()["conflict"]["kind"]) == (409, "keyword")


async def test_update_bad_form(client, owner, create):
    created = await create()
    r = await client.put(f"/autoreplies/{created['id']}", headers=owner, json=form(keywords=[]))
    assert r.status_code == 422


async def test_enabled_toggle(client, owner, create):
    created = await create()
    url = f"/autoreplies/{created['id']}/enabled"
    assert (await client.put(url, headers=owner, json={"enabled": False})).json()[
        "enabled"
    ] is False
    assert (await client.put(url, headers=owner, json={"enabled": True})).json()["enabled"] is True


async def test_archive_releases_word_and_post(client, owner, account, create, session):
    general = await create()
    own = await create(name="Пост", scope="posts", media_ids=["m1"])
    for autoreply in (general, own):
        r = await client.post(f"/autoreplies/{autoreply['id']}/archive", headers=owner)
        assert r.json()["archived_at"] is not None

    # в обычном списке их нет, в архиве есть
    params = {"account_id": str(account.id)}
    assert (await client.get("/autoreplies", headers=owner, params=params)).json() == []
    archived = await client.get("/autoreplies", headers=owner, params=params | {"archived": True})
    assert {a["id"] for a in archived.json()} == {general["id"], own["id"]}
    # флаг у поста стоит: на нём держится уникальный индекс
    flags = (await session.scalars(select(AutoreplyMedia.archived))).all()
    assert flags == [True]

    # слово и пост свободны
    await create()
    await create(name="Пост 2", scope="posts", media_ids=["m1"])


async def test_archive_twice_is_fine(client, owner, create):
    created = await create()
    with capture_logs() as logs:
        first = await client.post(f"/autoreplies/{created['id']}/archive", headers=owner)
        second = await client.post(f"/autoreplies/{created['id']}/archive", headers=owner)
    assert second.status_code == 200
    assert first.json()["archived_at"] == second.json()["archived_at"]
    # второй раз ничего не менял: now() в тесте стоит, поэтому смотрим по логу
    assert [e["event"] for e in logs].count("autoreply.archived") == 1


async def test_archived_cannot_be_edited(client, owner, create):
    created = await create()
    await client.post(f"/autoreplies/{created['id']}/archive", headers=owner)
    r = await client.put(f"/autoreplies/{created['id']}", headers=owner, json=form())
    assert (r.status_code, r.json()["detail"]) == (409, "AutoreplyArchived")
    r = await client.put(
        f"/autoreplies/{created['id']}/enabled", headers=owner, json={"enabled": False}
    )
    assert r.status_code == 409


async def test_unarchive(client, owner, create, session):
    created = await create(scope="posts", media_ids=["m1"])
    await client.post(f"/autoreplies/{created['id']}/archive", headers=owner)
    r = await client.post(f"/autoreplies/{created['id']}/unarchive", headers=owner)
    assert (r.status_code, r.json()["archived_at"]) == (200, None)
    assert (await session.scalars(select(AutoreplyMedia.archived))).all() == [False]
    # повтор ничего не ломает
    r = await client.post(f"/autoreplies/{created['id']}/unarchive", headers=owner)
    assert r.status_code == 200


@pytest.mark.parametrize(
    "taken",
    [
        {"keywords": ["гайд"]},
        {"name": "Пост", "scope": "posts", "media_ids": ["m1"], "keywords": ["другое"]},
    ],
)
async def test_unarchive_blocked_when_taken(client, owner, create, taken):
    if "media_ids" in taken:
        old = await create(scope="posts", media_ids=["m1"])
    else:
        old = await create()
    await client.post(f"/autoreplies/{old['id']}/archive", headers=owner)
    await create(**taken)

    r = await client.post(f"/autoreplies/{old['id']}/unarchive", headers=owner)
    assert (r.status_code, r.json()["detail"]) == (409, "AutoreplyConflict")
    # остался в архиве
    r = await client.get(f"/autoreplies/{old['id']}", headers=owner)
    assert r.json()["archived_at"] is not None


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PUT", "", form()),
        ("PUT", "/enabled", {"enabled": False}),
        ("POST", "/archive", None),
        ("POST", "/unarchive", None),
    ],
)
async def test_member_cannot_change(client, login_as, create, method, suffix, body):
    created = await create()
    member = await login_as("member")
    r = await client.request(
        method, f"/autoreplies/{created['id']}{suffix}", headers=member, json=body
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PUT", "", form()),
        ("PUT", "/enabled", {"enabled": False}),
        ("POST", "/archive", None),
        ("POST", "/unarchive", None),
    ],
)
async def test_unknown_autoreply(client, owner, method, suffix, body):
    r = await client.request(
        method, f"/autoreplies/{uuid.uuid7()}{suffix}", headers=owner, json=body
    )
    assert r.status_code == 404
