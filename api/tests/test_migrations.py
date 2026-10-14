"""Перенос данных в миграциях: на живой базе с прошлой версией схемы.

Основная тестовая база общая и уже на head, менять её схему посреди прогона нельзя.
Поэтому своя база: поднимаем до версии перед миграцией, кладём строки, как их
оставил старый код, поднимаем до head и смотрим, что стало."""

import json
import os
import subprocess
import sys
import uuid

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
