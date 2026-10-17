"""Песочница: как ответил бы ассистент с несохранёнными полями. Ничего не
отправляется, строки ответа нет, в предел не идёт, тратит деньги владельца."""

import uuid

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select

from app import ai
from app.assistant.models import Reply
from app.instagram.models import OutboxTask

CONNECTION = uuid.uuid7()


@pytest.fixture
async def owner(login_as):
    return await login_as("owner")


@pytest.fixture
def brain(monkeypatch):
    class Brain:
        calls: list[dict] = []
        answer = {"decision": "answer", "direct": "Нельзя.", "source": "С собакой"}
        fail: str | None = None

    async def run(*, purpose, scope, agent, prompt, using, **kw):
        Brain.calls.append({"purpose": purpose, "scope": scope, "prompt": prompt, "using": using})
        if Brain.fail:
            raise ai.AiCallFailed(Brain.fail)

        def model(messages, info: AgentInfo):
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, Brain.answer)])

        return await agent.run(prompt, model=FunctionModel(model))

    Brain.calls = []
    monkeypatch.setattr(ai, "run", run)
    return Brain


def body(**kw) -> dict:
    return {
        "mode": "direct",
        "instruction": "Пиши на «вы».",
        "knowledge": "С собакой: на Алтай нельзя.",
        "connection_id": str(CONNECTION),
        "model": "sonnet",
        "comment": "А с собакой можно?",
    } | kw


async def test_answer(client, owner, brain, session):
    assistant_id = uuid.uuid7()
    r = await client.post(
        "/assistants/try", headers=owner, json=body(assistant_id=str(assistant_id))
    )
    assert r.status_code == 200
    assert r.json() == {
        "decision": "answer",
        "comment": None,
        "direct": "Нельзя.",
        "source": "С собакой",
        "error": None,
    }
    [call] = brain.calls
    # своя задача: траты на проверки видны отдельно; модель из формы, не сохранённая
    assert (call["purpose"], call["scope"]) == ("assistant.try", str(assistant_id))
    assert call["using"] == ai.Using(CONNECTION, "sonnet")
    assert "А с собакой можно?" in call["prompt"]
    # ничего не ушло и в предел не пошло
    assert await session.scalar(select(func.count()).select_from(Reply)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxTask)) == 0


async def test_new_assistant_without_id(client, owner, brain):
    await client.post("/assistants/try", headers=owner, json=body())
    assert brain.calls[0]["scope"] is None


async def test_mode_rules_apply(client, owner, monkeypatch):
    # те же правила, что у живого ответа: в «кратко + директ» без коммента модель
    # переспрашивают, и в песочнице видно второй, правильный ответ
    answers = [
        {"decision": "answer", "direct": "Нельзя."},
        {"decision": "answer", "direct": "Нельзя.", "comment": "Нельзя, подробно в директе"},
    ]

    async def run(*, agent, prompt, **kw):
        def model(messages, info: AgentInfo):
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answers.pop(0))])

        return await agent.run(prompt, model=FunctionModel(model))

    monkeypatch.setattr(ai, "run", run)
    r = await client.post("/assistants/try", headers=owner, json=body(mode="combo"))
    assert r.json()["comment"] == "Нельзя, подробно в директе"
    assert answers == []


async def test_ai_failed_shows_code(client, owner, brain):
    brain.fail = "key_rejected"
    r = await client.post("/assistants/try", headers=owner, json=body())
    assert (r.status_code, r.json()["error"], r.json()["decision"]) == (200, "key_rejected", None)


@pytest.mark.parametrize(
    "kw",
    [{"comment": ""}, {"comment": "x" * 2201}, {"knowledge": "x" * 50_001}, {"model": " "}],
    ids=["empty", "long-comment", "long-base", "model"],
)
async def test_form_errors(client, owner, brain, kw):
    assert (await client.post("/assistants/try", headers=owner, json=body(**kw))).status_code == 422
    assert brain.calls == []


@pytest.mark.parametrize("granted", [False, True], ids=["member", "can_connect"])
async def test_only_owner(client, login_as, session, brain, granted):
    member = await login_as("member")
    if granted:
        from app.identity import repository as identity_repository

        user = await identity_repository.user_by_email(session, "member@test.dev")
        user.can_connect_accounts = True
        await session.commit()
    assert (await client.post("/assistants/try", headers=member, json=body())).status_code == 403
    assert brain.calls == []
