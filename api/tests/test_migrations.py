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


def journal(conn, kind: str, comment_id: str) -> None:
    conn.execute(
        "INSERT INTO activity.event (id, kind, comment_id) VALUES (%s, %s, %s)",
        (uuid.uuid4(), kind, comment_id),
    )


def test_inbox_handled_by_restored(db):
    alembic("upgrade", "ec8e58f0550d")
    # новая выдача и повтор того же человека: у повтора своей выдачи нет, только журнал
    inbox(db, "new", "comment", {"id": "c1"})
    journal(db, "comment.received", "c1")
    journal(db, "autoreply.matched", "c1")
    inbox(db, "repeat", "comment", {"id": "c2"})
    journal(db, "comment.received", "c2")
    journal(db, "autoreply.repeat_comment", "c2")
    # ни один автоответ не подошёл: пришёл, но никто не взял
    inbox(db, "nobody", "comment", {"id": "c3"})
    journal(db, "comment.received", "c3")
    inbox(db, "own", "comment", {"id": "c4"}, outcome="skipped")
    # нажатие нашей кнопки и чужой; сдавшееся не считается взятым
    inbox(db, "ours", "postback", {"postback": {"payload": "ar:1"}})
    inbox(db, "foreign", "postback", {"postback": {"payload": "other:1"}})
    inbox(db, "failed", "postback", {"postback": {"payload": "ar:2"}}, outcome="failed")

    alembic("upgrade", "head")

    rows = dict(db.execute("SELECT dedup_key, handled_by FROM instagram.inbox").fetchall())
    assert rows == {
        "new": "autoreplies",
        "repeat": "autoreplies",
        "nobody": None,
        "own": None,
        "ours": "autoreplies",
        "foreign": None,
        "failed": None,
    }
