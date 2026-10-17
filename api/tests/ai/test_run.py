"""ai.run: задача → подключение и модель → агент, каждый запрос строкой в
журнал, ошибки нашими кодами, поломка на карточку подключения. Сеть подменена,
сессии ai.run в тестах это сессия песочницы."""

import asyncio
import contextlib
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent
from sqlalchemy import select, update
from structlog.testing import capture_logs

from app import ai
from app.ai import calls
from app.ai.exceptions import ConnectionNotFound, ModelRequired
from app.ai.models import Binding, Call, Connection
from app.core import crypto
from tests.ai.test_anthropic import answer as anthropic_answer

PURPOSE = "assistant.answer"
SCOPE = "account-1"
MODEL = "anthropic/claude-haiku-5-5"
SOON = timedelta(hours=1)


def completion(request, content="ок", tool_calls=None):
    body = json.loads(request.content)
    if body.get("stream"):
        return stream(body["model"], content)
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message |= {"content": None, "tool_calls": tool_calls}
    return httpx2.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 1,
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                    "message": message,
                }
            ],
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 5,
                "total_tokens": 35,
                "prompt_tokens_details": {"cached_tokens": 20},
            },
        },
    )


def stream(model, content):
    """Ответ OpenAI-формата потоком: куски текста, потом usage и [DONE]."""
    base = {"id": "x", "object": "chat.completion.chunk", "created": 1, "model": model}
    chunks = [
        base | {"choices": [{"index": 0, "delta": {"role": "assistant", "content": content}}]},
        base | {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        base
        | {
            "choices": [],
            "usage": {"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35},
        },
    ]
    text = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(200, text=text, headers={"content-type": "text/event-stream"})


def status(code):
    return lambda request: httpx2.Response(code, json={"error": {"message": "x"}})


@pytest.fixture
def net(monkeypatch):
    class Net:
        seen: list = []
        answer = staticmethod(completion)

    async def handler(request):
        Net.seen.append(request)
        result = Net.answer(request)
        return await result if hasattr(result, "__await__") else result

    monkeypatch.setattr(
        calls, "_http", lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    Net.seen = []
    return Net


@pytest.fixture
def make_session(session):
    @asynccontextmanager
    async def same():
        yield session

    return same


async def add_connection(session, provider="timeweb", **kw) -> Connection:
    connection = Connection(
        **{
            "provider": provider,
            "name": provider,
            "key_encrypted": crypto.encrypt("sk-test-key-0123456789"),
            "key_hint": "6789",
            "key_changed_at": datetime.now(UTC) - SOON,
            "created_by": uuid.uuid7(),
        }
        | kw
    )
    session.add(connection)
    await session.commit()
    return connection


@pytest.fixture
async def connection(session) -> Connection:
    connection = await add_connection(session)
    await ai.set_binding(
        session, purpose=PURPOSE, scope=SCOPE, connection_id=connection.id, model=MODEL
    )
    await session.commit()
    return connection


async def run(make_session, agent=None, **kw):
    return await ai.run(
        purpose=PURPOSE,
        scope=SCOPE,
        agent=agent or Agent(),
        prompt="вопрос",
        make_session=make_session,
        **kw,
    )


async def failed(make_session, **kw) -> str:
    with pytest.raises(ai.AiCallFailed) as caught:
        await run(make_session, **kw)
    return caught.value.code


async def journal(session) -> list[Call]:
    return list(await session.scalars(select(Call).order_by(Call.started_at)))


async def fresh(session, row):
    await session.refresh(row)
    return row


async def test_answer_and_journal(session, make_session, net, connection):
    result = await run(make_session)
    assert result.output == "ок"
    [call] = await journal(session)
    assert (call.purpose, call.scope, call.provider, call.model) == (
        PURPOSE,
        SCOPE,
        "timeweb",
        MODEL,
    )
    assert (call.outcome, call.error_code, call.connection_id) == ("ok", None, connection.id)
    assert (call.input_tokens, call.output_tokens, call.cached_tokens) == (30, 5, 20)
    assert call.duration_ms >= 0
    # ключ из подключения, модель из настройки задачи
    request = net.seen[0]
    assert request.headers["authorization"] == "Bearer sk-test-key-0123456789"
    assert json.loads(request.content)["model"] == MODEL
    assert (await fresh(session, connection)).checked_at is not None


@pytest.mark.parametrize("scope", ["account-2", None])
async def test_not_configured(session, make_session, net, connection, scope):
    # у другого аккаунта и у задачи без области своей настройки нет
    with pytest.raises(ai.AiCallFailed, match=ai.NOT_CONFIGURED):
        await ai.run(
            purpose=PURPOSE, scope=scope, agent=Agent(), prompt="?", make_session=make_session
        )
    assert net.seen == []


async def test_deleted_connection_not_configured(session, make_session, net, connection):
    await session.delete(connection)
    await session.commit()
    assert await failed(make_session) == ai.NOT_CONFIGURED
    assert net.seen == []


async def test_unknown_provider_not_configured(session, make_session, net, connection):
    # строку записала версия новее, где провайдер есть, а у нас его нет
    await session.execute(update(Connection).values(provider="gigachat"))
    await session.commit()
    assert await failed(make_session) == ai.NOT_CONFIGURED


@pytest.mark.parametrize(("code", "error"), [(401, "key_rejected"), (402, "no_funds")])
async def test_broken_key_on_card(session, make_session, net, connection, code, error):
    net.answer = status(code)
    assert await failed(make_session) == error
    [call] = await journal(session)
    assert (call.outcome, call.error_code, call.http_status) == ("error", error, code)
    connection = await fresh(session, connection)
    assert (connection.error_code, connection.checked_at) == (error, None)
    assert connection.error_at == call.started_at


@pytest.mark.parametrize(
    ("answer", "code"),
    [(status(500), "server"), (status(429), "rate_limited")],
    ids=["500", "429"],
)
async def test_passing_failure_not_on_card(session, make_session, net, connection, answer, code):
    net.answer = answer
    assert await failed(make_session) == code
    [call] = await journal(session)
    assert call.error_code == code
    assert (await fresh(session, connection)).error_code is None


async def test_timeout(session, make_session, net, connection):
    def slow(request):
        raise httpx2.ReadTimeout("x", request=request)

    net.answer = slow
    assert await failed(make_session) == "timeout"
    assert [c.error_code for c in await journal(session)] == ["timeout"]


async def test_old_key_error_not_on_card(session, make_session, net, connection):
    # ключ заменили, пока шёл вызов со старым: его 401 новый не красит
    async def replace_meanwhile(request):
        await session.execute(update(Connection).values(key_changed_at=datetime.now(UTC) + SOON))
        await session.commit()
        return httpx2.Response(401, json={"error": {"message": "x"}})

    net.answer = replace_meanwhile
    assert await failed(make_session) == "key_rejected"
    assert (await fresh(session, connection)).error_code is None
    # но в журнале вызов есть: деньги и причина видны
    assert [c.error_code for c in await journal(session)] == ["key_rejected"]


async def test_success_clears_older_error(session, make_session, net, connection):
    connection.error_code, connection.error_at = "no_funds", datetime.now(UTC) - SOON
    await session.commit()
    await run(make_session)
    assert (await fresh(session, connection)).error_code is None


async def test_success_keeps_newer_error(session, make_session, net, connection):
    # ошибку записал вызов, начатый позже этого успеха: она свежее
    connection.error_code, connection.error_at = "no_funds", datetime.now(UTC) + SOON
    await session.commit()
    await run(make_session)
    connection = await fresh(session, connection)
    # и «проверен» старый успех не ставит: ошибка и проверка вместе не бывают
    assert (connection.error_code, connection.checked_at) == ("no_funds", None)


async def test_older_error_keeps_newer_error(session, make_session, net, connection):
    # опоздавший 402 от вызова, начатого раньше, не затирает свежий key_rejected
    connection.error_code, connection.error_at = "key_rejected", datetime.now(UTC) + SOON
    await session.commit()
    net.answer = status(402)
    await failed(make_session)
    assert (await fresh(session, connection)).error_code == "key_rejected"


async def test_error_older_than_success_not_on_card(session, make_session, net, connection):
    # успешный вызов, начатый позже, уже показал, что ключ в порядке
    connection.checked_at = datetime.now(UTC) + SOON
    await session.commit()
    net.answer = status(402)
    await failed(make_session)
    assert (await fresh(session, connection)).error_code is None


async def test_model_missing_marks_binding(session, make_session, net, connection):
    net.answer = status(404)
    assert await failed(make_session) == "model_missing"
    binding = await session.scalar(select(Binding))
    assert binding.model_missing_at is not None
    # ключ тут ни при чём
    assert (await fresh(session, connection)).error_code is None
    # дальше в сеть не ходим, пока владелец не выберет другую модель
    net.seen.clear()
    assert await failed(make_session) == "model_missing"
    assert net.seen == []
    # выбрал другую: пометка снята
    await ai.set_binding(
        session, purpose=PURPOSE, scope=SCOPE, connection_id=connection.id, model="other"
    )
    await session.commit()
    assert (await fresh(session, binding)).model_missing_at is None


async def test_model_changed_during_call(session, make_session, net, connection):
    # 404 был про старую модель, а владелец уже выбрал новую: новую не помечаем
    async def change_meanwhile(request):
        await session.execute(update(Binding).values(model="other"))
        await session.commit()
        return httpx2.Response(404, json={"error": {"message": "x"}})

    net.answer = change_meanwhile
    await failed(make_session)
    assert (await session.scalar(select(Binding))).model_missing_at is None


async def test_connection_deleted_during_call(session, make_session, net, connection):
    # журнал не теряет строку и не падает на внешнем ключе
    async def delete_meanwhile(request):
        await session.execute(Connection.__table__.delete())
        await session.commit()
        return completion(request)

    net.answer = delete_meanwhile
    assert (await run(make_session)).output == "ок"
    [call] = await journal(session)
    assert (call.connection_id, call.outcome) == (None, "ok")


async def test_tool_loop_stops_each_step_journaled(session, make_session, net, connection):
    agent = Agent()

    @agent.tool_plain
    def search_kb(query: str) -> str:
        return "ничего"

    def loop(request):
        n = len(net.seen)
        call = {
            "id": f"c{n}",
            "type": "function",
            "function": {"name": "search_kb", "arguments": '{"query": "q"}'},
        }
        return completion(request, tool_calls=[call])

    net.answer = loop
    assert await failed(make_session, agent=agent, steps=3) == ai.STEP_LIMIT
    assert [c.outcome for c in await journal(session)] == ["ok", "ok", "ok"]


async def test_bad_output(session, make_session, net, connection):
    class Pick(BaseModel):
        topic: int

    # модель дважды отвечает не по схеме: оба запроса в журнале, подключение ни при чём
    net.answer = lambda request: completion(request, content="не число")
    assert await failed(make_session, agent=Agent(output_type=Pick)) == ai.BAD_OUTPUT
    assert [c.outcome for c in await journal(session)] == ["ok", "ok"]
    assert (await fresh(session, connection)).error_code is None


async def test_unreadable_key(session, make_session, net, connection):
    await session.execute(update(Connection).values(key_encrypted="not-a-fernet-token"))
    await session.commit()
    assert await failed(make_session) == "key_unreadable"
    assert net.seen == []
    assert (await fresh(session, connection)).error_code == "key_unreadable"


async def test_anthropic_stream_journaled(session, make_session, net):
    # Anthropic для известных моделей отвечает потоком: строка журнала всё равно есть
    connection = await add_connection(session, provider="anthropic")
    await ai.set_binding(
        session,
        purpose=PURPOSE,
        scope=SCOPE,
        connection_id=connection.id,
        model="claude-haiku-5-5",
    )
    await session.commit()
    net.answer = lambda request: anthropic_answer(request, "ок")
    assert (await run(make_session)).output == "ок"
    assert json.loads(net.seen[0].content)["stream"] is True
    [call] = await journal(session)
    assert (call.provider, call.outcome, call.input_tokens, call.output_tokens) == (
        "anthropic",
        "ok",
        3,
        1,
    )


async def test_prompt_and_key_not_logged(session, make_session, net, connection):
    net.answer = status(401)
    with capture_logs() as logs, pytest.raises(ai.AiCallFailed):
        await ai.run(
            purpose=PURPOSE,
            scope=SCOPE,
            agent=Agent(),
            prompt="секретный коммент человека",
            make_session=make_session,
        )
    assert "секретный" not in str(logs) and "0123456789" not in str(logs)
    assert [e["event"] for e in logs] == ["ai.call.failed"]


async def test_set_binding_unknown_connection(session):
    with pytest.raises(ConnectionNotFound):
        await ai.set_binding(
            session, purpose=PURPOSE, scope=SCOPE, connection_id=uuid.uuid7(), model=MODEL
        )


async def test_set_binding_replaces(session, connection):
    other = await add_connection(session, name="второй")
    await ai.set_binding(session, purpose=PURPOSE, scope=SCOPE, connection_id=other.id, model="m")
    await session.commit()
    [binding] = list(await session.scalars(select(Binding)))
    assert (binding.connection_id, binding.model) == (other.id, "m")


async def test_stream_path_journaled(session, make_session, net, connection):
    # agent.run ходит через request, а поток (run_stream) через request_stream:
    # журнал должен считать и его, иначе предохранитель ассистента недосчитается
    target = await calls._target(make_session, PURPOSE, SCOPE)
    async with calls._http() as http:
        model = calls._Journaled(
            target.provider.model(http, key=target.key, base_url=None, model_id=MODEL),
            target,
            make_session,
        )
        async with Agent(model).run_stream("вопрос") as result:
            assert await result.get_output() == "ок"
    assert json.loads(net.seen[0].content)["stream"] is True
    [call] = await journal(session)
    assert (call.outcome, call.model, call.input_tokens) == ("ok", MODEL, 30)


def search_call(request):
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "search_kb", "arguments": '{"query": "q"}'},
    }
    return completion(request, tool_calls=[call])


@pytest.mark.parametrize(
    ("final", "before", "after"),
    [
        # старый ключ отозван: его 401 рабочий новый не красит
        (status(401), None, None),
        # старый ключ ответил: «нет денег» нового не снимает
        (completion, "no_funds", "no_funds"),
    ],
    ids=["401", "success"],
)
async def test_key_replaced_between_steps(
    session, make_session, net, connection, final, before, after
):
    # шаг 1 ушёл в инструмент, тем временем владелец заменил ключ; шаг 2 идёт
    # ещё со старым ключом, расшифрованным на старте запуска
    agent = Agent()

    @agent.tool_plain
    async def search_kb(query: str) -> str:
        now = datetime.now(UTC)
        await session.execute(
            update(Connection).values(
                key_changed_at=now, error_code=before, error_at=now if before else None
            )
        )
        await session.commit()
        return "ничего"

    net.answer = lambda request: search_call(request) if len(net.seen) == 1 else final(request)
    with contextlib.suppress(ai.AiCallFailed):
        await run(make_session, agent=agent)
    assert len(net.seen) == 2
    assert (await fresh(session, connection)).error_code == after


async def test_empty_answer_journaled(session, make_session, net, connection):
    # шлюз ответил 200 без choices, токены списаны: строка в журнале есть, наружу
    # AiCallFailed, как обещано, а не IndexError из глубин SDK
    def empty(request):
        response = completion(request)
        body = json.loads(response.content)
        return httpx2.Response(200, json=body | {"choices": []})

    net.answer = empty
    assert await failed(make_session) == "bad_response"
    [call] = await journal(session)
    assert (call.outcome, call.error_code) == ("error", "bad_response")
    assert (await fresh(session, connection)).error_code is None


async def test_tool_error_is_not_provider_failure(session, make_session, net, connection):
    # сеть упала в инструменте вызывающего, а не у провайдера: это его ошибка,
    # её не прячем под «провайдер сбоит» и в журнал как сбой вызова не пишем
    agent = Agent()

    @agent.tool_plain
    def search_kb(query: str) -> str:
        raise httpx2.ConnectError("база знаний недоступна")

    net.answer = search_call
    with pytest.raises(httpx2.ConnectError):
        await run(make_session, agent=agent)
    assert [c.outcome for c in await journal(session)] == ["ok"]


async def test_failure_without_provider_body(session, make_session, net, connection):
    # тело ответа провайдера бывает с кусками запроса: в цепочке исключения его нет
    net.answer = lambda request: httpx2.Response(
        400, json={"error": {"message": "в запросе: секретный коммент человека"}}
    )
    with pytest.raises(ai.AiCallFailed) as caught:
        await run(make_session)
    error = caught.value
    assert error.__cause__ is None and error.__suppress_context__
    # по всей цепочке, включая скрытый контекст и группы исключений: лог или
    # трейсбек покажут любое звено, а тело ответа не должно быть ни в одном
    texts = [f"{type(e).__name__}: {e!r} {e}" for e in chain(error)]
    assert not [t for t in texts if "секретный" in t], texts


def chain(error: BaseException) -> list[BaseException]:
    seen, todo = [], [error]
    while todo:
        e = todo.pop()
        if e is None or any(e is s for s in seen):
            continue
        seen.append(e)
        todo += [e.__cause__, e.__context__, *getattr(e, "exceptions", ())]
    return seen


async def test_set_binding_needs_model(session, connection):
    # пустая модель дала бы 404 на первом вызове и пометку «модели нет»
    with pytest.raises(ModelRequired):
        await ai.set_binding(
            session, purpose=PURPOSE, scope=SCOPE, connection_id=connection.id, model="  "
        )


async def test_step_limit_per_run_in_conversation(session, make_session, net, connection):
    # разговор в директе: каждое сообщение человека это свой запуск со своими
    # шагами, а не общий бюджет на весь разговор
    conversation = None
    for _ in range(7):
        result = await run(make_session, steps=2, conversation=conversation)
        conversation = result.conversation
    assert conversation.usage.requests == 7


async def test_step_limit_still_stops_loop_in_conversation(session, make_session, net, connection):
    # но зацикленный запуск внутри разговора всё равно стопорится на своих шагах
    conversation = (await run(make_session)).conversation
    agent = Agent()

    @agent.tool_plain
    def search_kb(query: str) -> str:
        return "ничего"

    net.answer = search_call
    net.seen.clear()
    assert (
        await failed(make_session, agent=agent, steps=3, conversation=conversation) == ai.STEP_LIMIT
    )
    assert len(net.seen) == 3


@pytest.mark.parametrize("change", ["connection", "key"])
async def test_model_missing_only_for_same_setting(session, make_session, net, connection, change):
    # пока шёл вызов, задачу перевели на другое подключение или заменили ключ:
    # 404 был про старую настройку и новую не блокирует
    other = await add_connection(session, name="второй")

    async def change_meanwhile(request):
        if change == "connection":
            await session.execute(update(Binding).values(connection_id=other.id))
        else:
            await session.execute(
                update(Connection)
                .where(Connection.id == connection.id)
                .values(key_changed_at=datetime.now(UTC))
            )
        await session.commit()
        return httpx2.Response(404, json={"error": {"message": "x"}})

    net.answer = change_meanwhile
    await failed(make_session)
    assert (await session.scalar(select(Binding))).model_missing_at is None


async def test_cancelled_request_journaled(session, make_session, net, connection):
    # вызывающий обернул ai.run в свой таймаут, а модель думает дольше: запрос
    # оборвался, но токены могли списать, и строка в журнале нужна
    async def slow(request):
        await asyncio.sleep(10)

    net.answer = slow
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.2):
            await run(make_session)
    [call] = await journal(session)
    assert (call.outcome, call.error_code) == ("error", "cancelled")
    assert (await fresh(session, connection)).error_code is None


async def test_stream_failure_without_provider_body(session, make_session, net, connection):
    # то же для потока (run_stream): тело ответа ни в одном звене цепочки
    net.answer = lambda request: httpx2.Response(
        400, json={"error": {"message": "в запросе: секретный коммент человека"}}
    )
    target = await calls._target(make_session, PURPOSE, SCOPE)
    async with calls._http() as http:
        model = calls._Journaled(
            target.provider.model(http, key=target.key, base_url=None, model_id=MODEL),
            target,
            make_session,
        )
        with pytest.raises(Exception) as caught:  # noqa: B017
            async with Agent(model).run_stream("вопрос") as result:
                await result.get_output()
    texts = [f"{type(e).__name__}: {e!r} {e}" for e in chain(caught.value)]
    assert not [t for t in texts if "секретный" in t], texts
