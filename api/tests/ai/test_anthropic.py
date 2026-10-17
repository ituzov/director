"""Anthropic: список моделей со страницами и возможностями, его ошибки, сборка
модели. Список из настоящего ответа Anthropic 2026-10-17 (data/anthropic_models.json)."""

import json
from pathlib import Path

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

from app.ai.providers import base
from app.ai.providers.anthropic import PAGE, VERSION, AnthropicProvider
from app.ai.providers.base import ModelInfo, ProviderError

LISTED = json.loads((Path(__file__).parent / "data" / "anthropic_models.json").read_text())


def client(handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


async def listed(handler=lambda request: httpx2.Response(200, json=LISTED), base_url=None):
    async with client(handler) as http:
        return await AnthropicProvider().models(http, key="k", base_url=base_url)


async def test_models_request():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200, json={"data": [], "has_more": False})

    await listed(handler)
    [request] = seen
    assert (request.url.host, request.url.path) == ("api.anthropic.com", "/v1/models")
    assert dict(request.url.params) == {"limit": str(PAGE)}
    # ключ в своём заголовке, Bearer Anthropic не принимает
    assert (request.headers["x-api-key"], request.headers["anthropic-version"]) == ("k", VERSION)
    assert "authorization" not in request.headers


async def test_models_with_names_and_strict_json():
    models = await listed()
    assert len(models) == len(LISTED["data"])
    assert models[0] == ModelInfo("claude-haiku-5-5", "Claude Haiku 5.5", True)


@pytest.mark.parametrize(
    ("capabilities", "strict"),
    [
        ({"structured_outputs": {"supported": False}}, False),
        ({}, None),
        (None, None),
        ({"structured_outputs": {"supported": "yes"}}, None),
    ],
    ids=["no", "unknown", "no-capabilities", "not-bool"],
)
async def test_strict_json_unknown_is_none(capabilities, strict):
    # возможностей нет или они непонятные: не знаем, а не «умеет»
    raw = {"id": "m", "display_name": "M", "capabilities": capabilities}
    [model] = await listed(lambda r: httpx2.Response(200, json={"data": [raw], "has_more": False}))
    assert model.strict_json is strict


async def test_models_pages():
    pages = {
        None: {"data": [{"id": "a"}, {"id": "b"}], "has_more": True, "last_id": "b"},
        "b": {"data": [{"id": "c"}], "has_more": False, "last_id": "c"},
    }
    seen = []

    def handler(request):
        after = request.url.params.get("after_id")
        seen.append(after)
        return httpx2.Response(200, json=pages[after])

    assert [m.id for m in await listed(handler)] == ["a", "b", "c"]
    assert seen == [None, "b"]


async def test_endless_pages_stop():
    # has_more не кончается: не крутимся вечно, а считаем, что провайдер сбоит
    calls = []

    def handler(request):
        calls.append(1)
        return httpx2.Response(200, json={"data": [{"id": "a"}], "has_more": True, "last_id": "a"})

    with pytest.raises(ProviderError) as caught:
        await listed(handler)
    assert caught.value.code == base.SERVER
    assert len(calls) == 10


@pytest.mark.parametrize(
    ("respond", "code", "status"),
    [
        (
            lambda r: httpx2.Response(
                401, json={"type": "error", "error": {"type": "authentication_error"}}
            ),
            base.KEY_REJECTED,
            401,
        ),
        # Anthropic перегружен
        (lambda r: httpx2.Response(529, json={"type": "error"}), base.SERVER, 529),
        (lambda r: httpx2.Response(200, text="<html>oops</html>"), base.SERVER, 200),
        (lambda r: httpx2.Response(200, json={"models": []}), base.SERVER, 200),
        (lambda r: httpx2.Response(200, json={"data": [], "has_more": True}), base.SERVER, 200),
    ],
    ids=["401", "529", "html", "other-format", "no-last-id"],
)
async def test_models_errors(respond, code, status):
    with pytest.raises(ProviderError) as caught:
        await listed(respond)
    assert (caught.value.code, caught.value.http_status) == (code, status)


async def test_models_timeout():
    def handler(request):
        raise httpx2.ReadTimeout("x", request=request)

    with pytest.raises(ProviderError, match=base.TIMEOUT):
        await listed(handler)


def answer(request: httpx2.Request, text: str) -> httpx2.Response:
    """Ответ Anthropic обычным JSON или потоком: длинные запросы (а для известных
    моделей Pydantic AI просит максимум токенов) SDK шлёт со stream=true."""
    body = json.loads(request.content)
    usage = {"input_tokens": 3, "output_tokens": 1}
    message = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": body["model"],
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": usage,
    }
    if not body.get("stream"):
        message |= {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}
        return httpx2.Response(200, json=message)
    events = [
        ("message_start", {"type": "message_start", "message": message}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": usage,
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    stream = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)
    return httpx2.Response(200, text=stream, headers={"content-type": "text/event-stream"})


async def test_model_talks_to_anthropic():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((request.url.path, request.headers["x-api-key"], body["model"]))
        return answer(request, "ок")

    async with client(handler) as http:
        model = AnthropicProvider().model(http, key="k", base_url=None, model_id="claude-haiku-5-5")
        result = await Agent(model).run("привет")
    assert result.output == "ок"
    assert seen == [("/v1/messages", "k", "claude-haiku-5-5")]


async def test_short_request_without_stream():
    # короткий ответ без потока тоже разбирается
    async with client(lambda request: answer(request, "да")) as http:
        model = AnthropicProvider().model(http, key="k", base_url=None, model_id="m")
        assert (await Agent(model).run("привет")).output == "да"


async def test_model_without_own_retries():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx2.Response(500, json={"type": "error", "error": {"type": "api_error"}})

    async with client(handler) as http:
        model = AnthropicProvider().model(http, key="k", base_url=None, model_id="m")
        with pytest.raises(ModelHTTPError):
            await Agent(model).run("привет")
    assert len(calls) == 1


async def test_owner_url_and_trailing_slash():
    seen = []

    def handler(request):
        seen.append(str(request.url.copy_with(query=None)))
        return httpx2.Response(200, json={"data": [], "has_more": False})

    await listed(handler, base_url="https://proxy.local/")
    assert seen == ["https://proxy.local/v1/models"]
