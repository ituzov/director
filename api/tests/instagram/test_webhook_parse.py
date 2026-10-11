"""Разбор пачки вебхука: что ложится во входящие, что пропускается."""

from app.instagram.webhook import dedup_key, parse_webhook

ACCOUNT = "17841400000000000"
COMMENT = {"id": "18000000000000001", "text": "хочу", "from": {"id": "1", "username": "x"}}
MESSAGE = {
    "sender": {"id": "1"},
    "recipient": {"id": ACCOUNT},
    "timestamp": 1791700000000,
    "message": {"mid": "aWdfZAm1", "text": "привет"},
}
POSTBACK = {
    "sender": {"id": "1"},
    "recipient": {"id": ACCOUNT},
    "timestamp": 1791700000000,
    "postback": {"mid": "aWdfZAm2", "payload": "GET_LINK", "title": "Получить"},
}


def entry(**kw) -> dict:
    return {"object": "instagram", "entry": [{"id": ACCOUNT, "time": 1791700000, **kw}]}


def test_comment():
    [item] = parse_webhook(entry(changes=[{"field": "comments", "value": COMMENT}])).items
    assert (item.ig_account_id, item.kind) == (ACCOUNT, "comment")
    assert item.dedup_key == dedup_key("comment", "18000000000000001")
    assert item.payload == COMMENT


def test_comment_on_entry_as_in_docs():
    body = {
        "object": "instagram",
        "entry": [{"id": ACCOUNT, "field": "comments", "value": COMMENT}],
    }
    [item] = parse_webhook(body).items
    assert (item.kind, item.dedup_key) == ("comment", dedup_key("comment", "18000000000000001"))


def test_message_and_postback():
    items = parse_webhook(entry(messaging=[MESSAGE, POSTBACK])).items
    assert [(i.kind, i.dedup_key) for i in items] == [
        ("message", dedup_key("message", "aWdfZAm1")),
        ("postback", dedup_key("postback", "aWdfZAm2")),
    ]
    # от сообщения храним событие целиком: кто, кому и когда
    assert items[0].payload == MESSAGE


def test_read():
    read = {"sender": {"id": "1"}, "recipient": {"id": ACCOUNT}, "read": {"mid": "aWdfZAm1"}}
    [item] = parse_webhook(entry(messaging=[read])).items
    assert (item.kind, item.dedup_key) == ("read", dedup_key("read", "1", "aWdfZAm1"))


def test_skipped_by_name():
    echo = {**MESSAGE, "message": {"mid": "aWdfZAm3", "is_echo": True}}
    reaction = {"sender": {"id": "1"}, "recipient": {"id": ACCOUNT}, "reaction": {"mid": "x"}}
    parsed = parse_webhook(
        entry(changes=[{"field": "mentions", "value": {"id": "5"}}], messaging=[echo, reaction])
    )
    assert parsed.items == []
    assert parsed.skipped == ["mentions", "echo", "reaction"]


def test_broken_shape_does_not_raise():
    # подпись наша, но форма неожиданная: пропускаем кусок, а не роняем вебхук
    for body in (None, [], {"entry": "x"}, {"entry": ["x", None, {"changes": [None, "x"]}]}):
        assert parse_webhook(body).items == []


def test_dedup_key_short_and_distinct():
    # настоящий mid у Instagram под 200 символов, а ключ всегда одной длины
    assert len(dedup_key("read", "1000000000000042", "aWdf" + "Z" * 200)) == len("read:") + 64
    # один id в разных видах это разные события
    assert dedup_key("message", "x") != dedup_key("postback", "x")
    # ключ стабилен: повтор того же события даёт тот же ключ
    assert dedup_key("comment", "1") == dedup_key("comment", 1)
