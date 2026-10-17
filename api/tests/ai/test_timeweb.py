"""Timeweb и общий OpenAI-формат: список моделей, его ошибки, сборка модели.
Список из настоящего ответа Timeweb 2026-10-17 (data/timeweb_models.json)."""

import json
from pathlib import Path

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

from app.ai.providers import base
from app.ai.providers.base import ProviderError
from app.ai.providers.openai_compatible import OpenAICompatible
from app.ai.providers.timeweb import TimewebProvider

LISTED = json.loads((Path(__file__).parent / "data" / "timeweb_models.json").read_text())


def client(handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


async def listed_ids(handler=lambda request: httpx2.Response(200, json=LISTED)) -> list[str]:
    async with client(handler) as http:
        return [m.id for m in await TimewebProvider().models(http, key="k", base_url=None)]


async def test_models_request():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"]))
        return httpx2.Response(200, json={"data": []})

    await listed_ids(handler)
    assert seen == [("https://api.timeweb.ai/v1/models", "Bearer k")]


@pytest.mark.parametrize(
    "model_id",
    [
        "anthropic/claude-haiku-5-5",
        "gemini/gemini-2.5-flash-lite",
        # без mode, но текстовые
        "yandex/yandexgpt-pro-5.1",
        "yandex/aliceai-llm-latest",
        "timeweb/glm-5.3",
    ],
)
async def test_text_models_listed(model_id):
    assert model_id in await listed_ids()


@pytest.mark.parametrize(
    "model_id",
    [
        # mode не chat: картинки, речь, эмбеддинги, только responses
        "gemini/gemini-3.1-flash-image-preview",
        "gemini/gemini-2.5-flash-preview-tts",
        "openai/gpt-5.3-codex",
        # без mode и не текст
        "runway/veo3.1",
        "black_forest_labs/flux-2-pro",
        "timeweb/bge-m3",
        "dashscope/text-embedding-v4",
    ],
)
async def test_not_text_models_hidden(model_id):
    assert model_id not in await listed_ids()


@pytest.mark.parametrize(
    ("respond", "code", "status"),
    [
        (lambda r: httpx2.Response(403, json={"error": {"message": "x"}}), base.KEY_REJECTED, 403),
        (lambda r: httpx2.Response(502, text="Bad Gateway"), base.SERVER, 502),
        # прокси отдал свою страницу вместо списка
        (lambda r: httpx2.Response(200, text="<html>oops</html>"), base.SERVER, 200),
        (lambda r: httpx2.Response(200, json={"models": []}), base.SERVER, 200),
        # элемент списка не объект: формат другой, а не 500 в ручке
        (lambda r: httpx2.Response(200, json={"data": ["gpt"]}), base.SERVER, 200),
    ],
    ids=["403", "502", "html", "other-format", "item-not-object"],
)
async def test_models_errors(respond, code, status):
    with pytest.raises(ProviderError) as caught:
        await listed_ids(respond)
    assert (caught.value.code, caught.value.http_status) == (code, status)


@pytest.mark.parametrize(
    ("exc", "code"),
    [(httpx2.ReadTimeout, base.TIMEOUT), (httpx2.RemoteProtocolError, base.SERVER)],
    ids=["timeout", "disconnect"],
)
async def test_models_no_answer(exc, code):
    def handler(request):
        raise exc("x", request=request)

    with pytest.raises(ProviderError) as caught:
        await listed_ids(handler)
    assert (caught.value.code, caught.value.http_status) == (code, None)


async def test_check_key_is_models_request():
    async with client(lambda r: httpx2.Response(200, json={"data": []})) as http:
        await TimewebProvider().check_key(http, key="k", base_url=None)
    async with client(lambda r: httpx2.Response(403, json={})) as http:
        with pytest.raises(ProviderError, match=base.KEY_REJECTED):
            await TimewebProvider().check_key(http, key="k", base_url=None)


async def test_model_talks_to_timeweb():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((str(request.url), request.headers["authorization"], body["model"]))
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
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ок"},
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            },
        )

    async with client(handler) as http:
        model = TimewebProvider().model(
            http, key="k", base_url=None, model_id="anthropic/claude-haiku-5-5"
        )
        result = await Agent(model).run("привет")
    assert result.output == "ок"
    assert seen == [
        ("https://api.timeweb.ai/v1/chat/completions", "Bearer k", "anthropic/claude-haiku-5-5")
    ]


async def test_model_without_own_retries():
    # повторяет сервис ai, а не SDK: иначе один вызов уйдёт в сеть трижды мимо журнала
    calls = []

    def handler(request):
        calls.append(1)
        return httpx2.Response(500, json={"error": {"message": "x"}})

    async with client(handler) as http:
        model = TimewebProvider().model(http, key="k", base_url=None, model_id="m")
        with pytest.raises(ModelHTTPError):
            await Agent(model).run("привет")
    assert len(calls) == 1


async def test_owner_url_wins_and_trailing_slash():
    class Own(OpenAICompatible):
        kind = "own"
        needs_base_url = True

    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx2.Response(200, json={"data": [{"id": "llama"}]})

    async with client(handler) as http:
        listed = await Own().models(http, key="k", base_url="http://gpu.local:8000/v1/")
    assert (seen, [m.id for m in listed]) == (["http://gpu.local:8000/v1/models"], ["llama"])
    with pytest.raises(ValueError, match="адрес"):
        Own().url(None)


async def test_owner_url_over_known():
    # владелец поставил свой прокси перед известным провайдером: идём на его адрес
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx2.Response(200, json={"data": []})

    async with client(handler) as http:
        await TimewebProvider().models(http, key="k", base_url="https://proxy.local/v1")
    assert seen == ["https://proxy.local/v1/models"]


async def test_models_use_provider_status_rule():
    # провайдер уточнил перевод статуса: список моделей идёт по нему, а не по общему
    class Quirky(TimewebProvider):
        def error_code(self, status):
            return base.NO_FUNDS if status == 400 else super().error_code(status)

    async with client(lambda r: httpx2.Response(400, json={})) as http:
        with pytest.raises(ProviderError, match=base.NO_FUNDS):
            await Quirky().models(http, key="k", base_url=None)
