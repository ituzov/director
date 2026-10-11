"""Ручки автоответов: форма проверяется до базы, слова и посты не делятся,
создаёт тот, кто может подключать аккаунты, смотрят все вошедшие."""

import uuid

import pytest

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


def form(account: Account, **kw) -> dict:
    return {
        "account_id": str(account.id),
        "name": "Гайд",
        "scope": "all",
        # не по алфавиту: проверяем, что слова возвращаются в порядке ввода
        "keywords": ["хочу гайд", "Гайд"],
        "intro_text": "Держи 👇",
        "button_text": "Получить",
        "reply_text": "https://example.com/guide",
    } | kw


async def create(client, headers, body):
    return await client.post("/autoreplies", headers=headers, json=body)


async def test_create_and_read(client, owner, account):
    r = await create(client, owner, form(account, comment_replies=["Отправили!", "Лови в директе"]))
    assert r.status_code == 201
    body = r.json()
    assert body["keywords"] == ["хочу гайд", "Гайд"]
    assert body["comment_replies"] == ["Отправили!", "Лови в директе"]
    assert body["comment_reply_mode"] == "random"
    assert (body["enabled"], body["archived_at"], body["media_ids"]) == (True, None, [])

    assert (await client.get(f"/autoreplies/{body['id']}", headers=owner)).json() == body
    r = await client.get("/autoreplies", headers=owner, params={"account_id": str(account.id)})
    assert r.json() == [body]


async def test_comment_replies_in_sequence(client, owner, account):
    r = await create(client, owner, form(account, comment_reply_mode="sequence"))
    assert r.json()["comment_reply_mode"] == "sequence"


async def test_create_for_posts(client, owner, account):
    r = await create(client, owner, form(account, scope="posts", media_ids=["m2", "m1"]))
    assert r.json()["media_ids"] == ["m1", "m2"]


async def test_text_trimmed(client, owner, account):
    r = await create(client, owner, form(account, name="  Гайд ", keywords=[" гайд "]))
    assert (r.json()["name"], r.json()["keywords"]) == ("Гайд", ["гайд"])


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"keywords": []}, None),
        ({"keywords": ["🔥"]}, "keyword_empty"),
        ({"keywords": ["Гайд", "гайд!"]}, "keyword_duplicate"),
        ({"scope": "posts"}, "posts_required"),
        ({"media_ids": ["m1"]}, "posts_not_allowed"),
        ({"scope": "posts", "media_ids": ["m1", "m1"]}, "post_duplicate"),
        ({"follow_gate": True}, "not_following_text_required"),
        ({"button_text": "x" * 21}, None),
        # материал: 501 кириллическая буква это 1002 байта
        ({"reply_text": "я" * 501}, "message_too_long"),
        # с кнопкой: до 640 знаков
        ({"intro_text": "x" * 641}, None),
        ({"follow_gate": True, "not_following_text": "x" * 641}, None),
        ({"reply_text": "   "}, None),
        ({"comment_replies": ["ок"] * 11}, None),
        ({"scope": "some"}, None),
        ({"comment_reply_mode": "shuffle"}, None),
    ],
)
async def test_bad_form(client, owner, account, change, code):
    r = await create(client, owner, form(account, **change))
    assert r.status_code == 422
    if code:
        assert code in str(r.json())


async def test_button_message_up_to_640_chars(client, owner, account):
    # 640 кириллических знаков это 1280 байт: лимит у кнопочного сообщения в знаках
    r = await create(client, owner, form(account, intro_text="я" * 640))
    assert r.status_code == 201


async def test_follow_gate_with_text(client, owner, account):
    r = await create(
        client, owner, form(account, follow_gate=True, not_following_text="Подпишись 🙂")
    )
    assert r.status_code == 201


async def test_general_word_taken(client, owner, account):
    first = (await create(client, owner, form(account))).json()
    r = await create(client, owner, form(account, name="Второй", keywords=["прайс", "ГАЙД"]))
    assert r.status_code == 409
    assert r.json() == {
        "detail": "AutoreplyConflict",
        "conflict": {
            "kind": "keyword",
            "value": "ГАЙД",
            "autoreply": {"id": first["id"], "name": "Гайд", "enabled": True},
        },
    }


async def test_disabled_general_still_holds_word(client, owner, account):
    await create(client, owner, form(account, enabled=False))
    r = await create(client, owner, form(account, keywords=["гайд"]))
    assert r.json()["conflict"]["autoreply"]["enabled"] is False


async def test_posts_and_general_share_words(client, owner, account):
    await create(client, owner, form(account))
    # частный с тем же словом: разные уровни, под своим постом он главнее
    r = await create(client, owner, form(account, scope="posts", media_ids=["m1"]))
    assert r.status_code == 201


async def test_word_of_posts_autoreply_free_for_general(client, owner, account):
    await create(client, owner, form(account, scope="posts", media_ids=["m1"]))
    assert (await create(client, owner, form(account))).status_code == 201


async def test_post_taken(client, owner, account):
    first = (await create(client, owner, form(account, scope="posts", media_ids=["m1"]))).json()
    r = await create(
        client, owner, form(account, name="Другой", scope="posts", media_ids=["m2", "m1"])
    )
    assert r.status_code == 409
    assert r.json()["conflict"] == {
        "kind": "post",
        "value": "m1",
        "autoreply": {"id": first["id"], "name": "Гайд", "enabled": True},
    }


async def test_other_account_words_free(client, owner, account, session):
    other = Account(
        ig_user_id="17841400000000001",
        username="other",
        token_encrypted="x",
        connected_by=uuid.uuid7(),
    )
    session.add(other)
    await session.commit()
    await create(client, owner, form(account))
    assert (await create(client, owner, form(other))).status_code == 201


@pytest.mark.parametrize("status", [None, "disconnected"])
async def test_account_unavailable(client, owner, account, session, status):
    if status:
        account.status, account.token_encrypted = status, None
        await session.commit()
        body = form(account)
    else:
        body = form(account) | {"account_id": str(uuid.uuid7())}
    r = await create(client, owner, body)
    assert (r.status_code, r.json()["detail"]) == (409, "AccountUnavailable")


async def test_unknown_autoreply(client, owner):
    r = await client.get(f"/autoreplies/{uuid.uuid7()}", headers=owner)
    assert (r.status_code, r.json()["detail"]) == (404, "AutoreplyNotFound")


async def test_list_by_account(client, owner, account):
    await create(client, owner, form(account))
    r = await client.get("/autoreplies", headers=owner, params={"account_id": str(uuid.uuid7())})
    assert r.json() == []
    r = await client.get(
        "/autoreplies", headers=owner, params={"account_id": str(account.id), "archived": True}
    )
    assert r.json() == []


async def test_member_reads_but_cannot_create(client, login_as, account, owner):
    created = (await create(client, owner, form(account))).json()
    member = await login_as("member")
    assert (await create(client, member, form(account, keywords=["прайс"]))).status_code == 403
    assert (await client.get(f"/autoreplies/{created['id']}", headers=member)).status_code == 200


async def test_anonymous_rejected(client, account):
    assert (await create(client, {}, form(account))).status_code == 401
    r = await client.get("/autoreplies", params={"account_id": str(account.id)})
    assert r.status_code == 401
