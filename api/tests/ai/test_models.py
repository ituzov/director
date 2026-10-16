"""Модели ai: инварианты держит база, а не только код."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.ai.models import Binding, Call, Connection

T0 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


def make_connection(**kw) -> Connection:
    return Connection(
        **{
            "provider": "timeweb",
            "name": "Timeweb",
            "key_encrypted": "x",
            "key_hint": "RGQ",
            "created_by": uuid.uuid7(),
        }
        | kw
    )


def make_call(**kw) -> Call:
    return Call(
        **{
            "started_at": T0,
            "duration_ms": 120,
            "purpose": "autoreplies.suggest",
            "provider": "timeweb",
            "model": "anthropic/claude-haiku-5-5",
            "outcome": "ok",
        }
        | kw
    )


async def add(session, *rows):
    session.add_all(rows)
    await session.commit()


@pytest.mark.parametrize(
    "error", [{"error_code": "key_rejected"}, {"error_at": T0}], ids=["code", "time"]
)
async def test_connection_error_is_whole(session, error):
    # код без времени не сравнить с началом вызова, время без кода ничего не говорит
    session.add(make_connection(**error))
    with pytest.raises(IntegrityError, match="ck_connection_error_complete"):
        await session.commit()


async def test_connection_error_with_time(session):
    await add(session, make_connection(error_code="key_rejected", error_at=T0))


@pytest.mark.parametrize(
    ("outcome", "error_code"), [("error", None), ("ok", "timeout")], ids=["error", "ok"]
)
async def test_call_error_code_only_on_error(session, outcome, error_code):
    session.add(make_call(outcome=outcome, error_code=error_code))
    with pytest.raises(IntegrityError, match="ck_call_error_when_failed"):
        await session.commit()


async def test_call_unknown_outcome_rejected(session):
    session.add(make_call(outcome="maybe"))
    with pytest.raises(IntegrityError, match="ck_call_outcome_known"):
        await session.commit()


async def test_failed_call_with_code(session):
    await add(session, make_call(outcome="error", error_code="timeout"))


async def test_one_binding_per_purpose_without_scope(session):
    # у задачи на всю установку области нет, но вторая строка всё равно лишняя
    await add(session, Binding(purpose="autoreplies.suggest", model="m"))
    session.add(Binding(purpose="autoreplies.suggest", model="m2"))
    with pytest.raises(IntegrityError, match="uq_binding_purpose_scope"):
        await session.commit()


async def test_one_binding_per_purpose_and_scope(session):
    await add(session, Binding(purpose="assistant.answer", scope="a1", model="m"))
    session.add(Binding(purpose="assistant.answer", scope="a1", model="m2"))
    with pytest.raises(IntegrityError, match="uq_binding_purpose_scope"):
        await session.commit()


async def test_bindings_of_different_scopes(session):
    # ассистент каждого аккаунта выбирает модель сам
    await add(
        session,
        Binding(purpose="assistant.answer", scope="a1", model="m"),
        Binding(purpose="assistant.answer", scope="a2", model="m"),
        Binding(purpose="assistant.answer", model="m"),
    )


async def test_deleted_connection_keeps_binding_and_calls(session):
    # отключили ключ: задача остаётся «не настроенной», журнал вызовов не теряется
    connection = make_connection()
    await add(session, connection)
    binding = Binding(purpose="autoreplies.suggest", connection_id=connection.id, model="m")
    call = make_call(connection_id=connection.id)
    await add(session, binding, call)

    await session.delete(connection)
    await session.commit()
    await session.refresh(binding)
    await session.refresh(call)
    assert (binding.connection_id, call.connection_id) == (None, None)
