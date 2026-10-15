"""Перенос данных в миграциях: на живой базе с прошлой версией схемы.

Основная тестовая база общая и уже на head, менять её схему посреди прогона нельзя.
Поэтому своя база: поднимаем до версии перед миграцией, кладём строки, как их
оставил старый код, поднимаем до head и смотрим, что стало."""

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from tests.conftest import API_DIR, TEST_DATABASE_URL

DB_NAME = "director_migrations_test"
DB_URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + f"/{DB_NAME}"
SERVER = TEST_DATABASE_URL.replace("+psycopg", "").rsplit("/", 1)[0]


def alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": DB_URL},
        cwd=API_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} упал:\n{result.stderr}")


@pytest.fixture
def db():
    """Пустая база только для этого теста; после него удаляется."""
    with psycopg.connect(f"{SERVER}/postgres", autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{DB_NAME}"')
    try:
        with psycopg.connect(f"{SERVER}/{DB_NAME}", autocommit=True) as conn:
            yield conn
    finally:
        with psycopg.connect(f"{SERVER}/postgres", autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


def inbox(conn, key: str, kind: str, payload: dict, outcome: str = "done") -> None:
    conn.execute(
        """INSERT INTO instagram.inbox
           (id, ig_account_id, kind, dedup_key, payload, outcome, processed_at)
           VALUES (%s, '1', %s, %s, %s, %s, now())""",
        (uuid.uuid4(), kind, key, json.dumps(payload), outcome),
    )


def journal(
    conn, kind: str, comment_id: str | None, autoreply_id=None, data=None, person_id="p1"
) -> None:
    conn.execute(
        """INSERT INTO activity.event (id, kind, comment_id, autoreply_id, data, person_id)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (uuid.uuid4(), kind, comment_id, autoreply_id, json.dumps(data or {}), person_id),
    )


def test_inbox_handled_restored(db):
    """Кто и какой автоответ взял прошлые события: по журналу activity."""
    alembic("upgrade", "ec8e58f0550d")
    guide, other = uuid.uuid4(), uuid.uuid4()
    d1, d2 = uuid.uuid4(), uuid.uuid4()
    # новая выдача и повтор того же человека: у повтора своей выдачи нет, только журнал
    inbox(db, "new", "comment", {"id": "c1"})
    journal(db, "comment.received", "c1")
    journal(db, "autoreply.matched", "c1", guide)
    inbox(db, "repeat", "comment", {"id": "c2"})
    journal(db, "comment.received", "c2")
    journal(db, "autoreply.repeat_comment", "c2", other)
    # ни один автоответ не подошёл: пришёл, но никто не взял
    inbox(db, "nobody", "comment", {"id": "c3"})
    journal(db, "comment.received", "c3")
    inbox(db, "own", "comment", {"id": "c4"}, outcome="skipped")
    # нажатие нашей кнопки: автоответ по выдаче из журнала нажатий
    inbox(db, "ours", "postback", {"sender": {"id": "p1"}, "postback": {"payload": f"ar:{d1}"}})
    journal(db, "autoreply.clicked", "c1", guide, {"delivery_id": str(d1)})
    # ту же кнопку нажал другой человек: обработчик его отклонил, в журнале его нет
    inbox(db, "stranger", "postback", {"sender": {"id": "p2"}, "postback": {"payload": f"ar:{d1}"}})
    # кнопка наша, но в журнале её нет (нажал не тот): взяли, автоответ не определить
    inbox(db, "ours-unknown", "postback", {"postback": {"payload": f"ar:{d2}"}})
    inbox(db, "foreign", "postback", {"postback": {"payload": "other:1"}})
    inbox(db, "failed", "postback", {"postback": {"payload": f"ar:{d1}"}}, outcome="failed")

    alembic("upgrade", "head")

    rows = {
        key: (by, ref)
        for key, by, ref in db.execute(
            "SELECT dedup_key, handled_by, handled_ref FROM instagram.inbox"
        ).fetchall()
    }
    assert rows == {
        "new": ("autoreplies", str(guide)),
        "repeat": ("autoreplies", str(other)),
        "nobody": (None, None),
        "own": (None, None),
        "ours": ("autoreplies", str(guide)),
        "stranger": ("autoreplies", None),
        "ours-unknown": ("autoreplies", None),
        "foreign": (None, None),
        "failed": (None, None),
    }


def delivery(conn, autoreply_id, name: str, **at) -> uuid.UUID:
    delivery_id = uuid.uuid4()
    conn.execute(
        """INSERT INTO autoreplies.delivery
           (id, autoreply_id, account_id, comment_id, media_id, person_id, keyword,
            sent_at, clicked_at, delivered_at)
           VALUES (%s, %s, %s, %s, 'm1', %s, 'гайд', %s, %s, %s)""",
        (
            delivery_id,
            autoreply_id,
            uuid.uuid4(),
            name,
            name,
            at.get("sent"),
            at.get("clicked"),
            at.get("delivered"),
        ),
    )
    return delivery_id


def step(conn, kind: str, delivery_id, minute: int, **data) -> None:
    conn.execute(
        """INSERT INTO activity.event (id, kind, comment_id, data, occurred_at)
           VALUES (%s, %s, 'c', %s, %s)""",
        (
            uuid.uuid4(),
            kind,
            json.dumps({"delivery_id": str(delivery_id)} | data),
            datetime(2026, 1, 2, 12, minute, tzinfo=UTC),
        ),
    )


def test_delivery_stage_restored(db):
    """Этап прошлых выдач: по полям выдачи, уточнённый последним событием журнала."""
    alembic("upgrade", "207c348721e9")
    autoreply_id = uuid.uuid4()
    db.execute(
        """INSERT INTO autoreplies.autoreply
           (id, account_id, name, scope, intro_text, button_text, reply_text, created_by,
            enabled, follow_gate)
           VALUES (%s, %s, 'Гайд', 'all', 'Держи', 'Получить', 'ссылка', %s, true, false)""",
        (autoreply_id, uuid.uuid4(), uuid.uuid4()),
    )
    now = "2026-01-02 12:00+00"
    # журнала нет: только по полям
    delivery(db, autoreply_id, "fresh")
    delivery(db, autoreply_id, "sent", sent=now)
    delivery(db, autoreply_id, "got", sent=now, clicked=now, delivered=now)
    delivery(db, autoreply_id, "pressed", sent=now, clicked=now)
    # что попросили подписаться и что не ушло, видно только в журнале
    asked = delivery(db, autoreply_id, "asked", sent=now, clicked=now)
    step(db, "autoreply.sent", asked, 1)
    step(db, "autoreply.clicked", asked, 2)
    step(db, "autoreply.follow_asked", asked, 3)
    # ответ под комментом пришёл последним: этап не меняет
    step(db, "autoreply.commented", asked, 4)
    # только сработал: директ ещё в очереди, журнал это подтверждает
    matched = delivery(db, autoreply_id, "matched", sent=now)
    step(db, "autoreply.matched", matched, 1)
    polite = delivery(db, autoreply_id, "polite", sent=now)
    step(db, "autoreply.sent", polite, 1)
    step(db, "autoreply.send_failed", polite, 2, stage="comment")
    dm_lost = delivery(db, autoreply_id, "dm_lost")
    step(db, "autoreply.send_failed", dm_lost, 1, stage="intro")
    lost = delivery(db, autoreply_id, "lost", sent=now, clicked=now)
    step(db, "autoreply.send_failed", lost, 3, stage="material")
    # провалился материал, потом человек нажал снова: последнее событие решает
    again = delivery(db, autoreply_id, "again", sent=now, clicked=now)
    step(db, "autoreply.send_failed", again, 3, stage="material")
    step(db, "autoreply.clicked", again, 4)
    # выдан: журнал со старой ошибкой его не перебивает
    done = delivery(db, autoreply_id, "done", sent=now, clicked=now, delivered=now)
    step(db, "autoreply.send_failed", done, 9, stage="material")

    alembic("upgrade", "head")

    stages = dict(db.execute("SELECT comment_id, stage FROM autoreplies.delivery").fetchall())
    assert stages == {
        "fresh": "sending",
        "sent": "waiting_click",
        "got": "delivered",
        "pressed": "clicked",
        "polite": "waiting_click",
        "matched": "sending",
        "asked": "follow_asked",
        "dm_lost": "dm_failed",
        "lost": "material_failed",
        "again": "clicked",
        "done": "delivered",
    }


def test_delivery_stage_at_restored(db):
    """Время этапа прошлых выдач: последнее событие, которое двигает этап; без журнала
    время выдачи. Иначе now() миграции не пустил бы ни один запоздалый отчёт."""
    alembic("upgrade", "5d63c70acbd8")
    autoreply_id = uuid.uuid4()
    db.execute(
        """INSERT INTO autoreplies.autoreply
           (id, account_id, name, scope, intro_text, button_text, reply_text, created_by,
            enabled, follow_gate)
           VALUES (%s, %s, 'Гайд', 'all', 'Держи', 'Получить', 'ссылка', %s, true, false)""",
        (autoreply_id, uuid.uuid4(), uuid.uuid4()),
    )
    quiet = delivery(db, autoreply_id, "quiet")
    db.execute(
        "UPDATE autoreplies.delivery SET created_at = %s WHERE id = %s",
        (datetime(2026, 1, 1, tzinfo=UTC), quiet),
    )
    busy = delivery(db, autoreply_id, "busy")
    step(db, "autoreply.sent", busy, 1)
    step(db, "autoreply.clicked", busy, 2)
    # ответ под комментом позже, но этап не двигает: его время не берём
    step(db, "autoreply.commented", busy, 5)

    alembic("upgrade", "head")

    rows = dict(db.execute("SELECT comment_id, stage_at FROM autoreplies.delivery").fetchall())
    assert rows == {
        "quiet": datetime(2026, 1, 1, tzinfo=UTC),
        "busy": datetime(2026, 1, 2, 12, 2, tzinfo=UTC),
    }
