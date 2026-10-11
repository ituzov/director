"""Разбор вебхука Meta: что из пачки ложится во входящие. Без базы и сети.

Комменты приходят в entry[].changes[], сообщения и кнопки в entry[].messaging[].
Подпись проверена до разбора, но форму пачки всё равно не принимаем на веру:
кривой кусок пропускаем, а не роняем весь вебхук, иначе Meta повторяет его бесконечно.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

COMMENT = "comment"
MESSAGE = "message"
POSTBACK = "postback"
# прочтение: человек прочитал всё до этого mid включительно, для статистики воронки
READ = "read"

# в событии messaging это служебные ключи, а не вид события
_ENVELOPE = {"sender", "recipient", "timestamp"}


@dataclass(frozen=True, slots=True)
class InboxItem:
    ig_account_id: str
    kind: str
    # вид и хэш id: mid у Instagram под 200 символов, а ключ нужен короткий и одной длины
    dedup_key: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Parsed:
    items: list[InboxItem] = field(default_factory=list)
    # имена пропущенного (reaction, echo, mentions): содержимое в лог не идёт
    skipped: list[str] = field(default_factory=list)


def parse_webhook(body: Any) -> Parsed:
    parsed = Parsed()
    for entry in _list(_dict(body).get("entry")):
        entry = _dict(entry)
        account = str(entry.get("id", ""))
        for change in _list(entry.get("changes")):
            _parse_change(parsed, account, _dict(change))
        # так коммент рисует дока Instagram Login: field и value прямо в entry.
        # Вживую 2026-10-10 он пришёл в changes[], но терять коммент из-за формы дороже ветки
        if "field" in entry:
            _parse_change(parsed, account, entry)
        for event in _list(entry.get("messaging")):
            _parse_messaging(parsed, account, _dict(event))
    return parsed


def _parse_change(parsed: Parsed, account: str, change: dict) -> None:
    value = _dict(change.get("value"))
    if change.get("field") == "comments" and value.get("id"):
        parsed.items.append(InboxItem(account, COMMENT, dedup_key(COMMENT, value["id"]), value))
    else:
        parsed.skipped.append(str(change.get("field")))


def _parse_messaging(parsed: Parsed, account: str, event: dict) -> None:
    message = _dict(event.get("message"))
    postback = _dict(event.get("postback"))
    read = _dict(event.get("read"))
    if message.get("is_echo"):
        # наши же исходящие: Meta возвращает их эхом
        parsed.skipped.append("echo")
    elif message.get("mid"):
        parsed.items.append(InboxItem(account, MESSAGE, dedup_key(MESSAGE, message["mid"]), event))
    elif postback.get("mid"):
        parsed.items.append(
            InboxItem(account, POSTBACK, dedup_key(POSTBACK, postback["mid"]), event)
        )
    elif read.get("mid"):
        # в ключе и человек: стоит копейки, а уникальность mid между людьми мы не проверяли
        sender = _dict(event.get("sender")).get("id")
        parsed.items.append(InboxItem(account, READ, dedup_key(READ, sender, read["mid"]), event))
    else:
        parsed.skipped.append(next((key for key in event if key not in _ENVELOPE), "unknown"))


def dedup_key(kind: str, *ids: object) -> str:
    """Ключ повтора: вид читаемо, id хэшем. Префикс вида разводит пространства id."""
    digest = hashlib.sha256(":".join(str(i) for i in ids).encode()).hexdigest()
    return f"{kind}:{digest}"


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []
