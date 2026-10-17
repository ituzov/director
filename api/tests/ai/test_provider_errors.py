"""Ошибки провайдера нашими кодами. Гоняем через настоящий путь (агент, SDK,
подделка сети) для обоих SDK: новая версия может заворачивать ошибки иначе."""

import httpx2
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from app.ai.providers import base
from app.ai.providers.base import Provider, ProviderError


class OpenAIFormat(Provider):
    kind = "test-openai"

    def model(self, http, *, key, base_url, model_id):
        client = AsyncOpenAI(
            base_url="https://x.test/v1", api_key=key, max_retries=0, http_client=http
        )
        return OpenAIChatModel(model_id, provider=OpenAIProvider(openai_client=client))

    async def models(self, http, *, key, base_url):
        return []


class AnthropicFormat(OpenAIFormat):
    kind = "test-anthropic"

    def model(self, http, *, key, base_url, model_id):
        client = AsyncAnthropic(api_key=key, max_retries=0, http_client=http)
        return AnthropicModel(model_id, provider=AnthropicProvider(anthropic_client=client))


def failing(kind: str):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if kind == "timeout":
            raise httpx2.ReadTimeout("timeout", request=request)
        if kind == "connect":
            raise httpx2.ConnectError("refused", request=request)
        if kind == "disconnect":
            raise httpx2.RemoteProtocolError("Server disconnected", request=request)
        return httpx2.Response(int(kind), json={"error": {"type": "x", "message": "x"}})

    return handler


async def run_error(provider: Provider, kind: str) -> BaseException:
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(failing(kind))) as http:
        model = provider.model(http, key="k", base_url=None, model_id="m")
        with pytest.raises(Exception) as caught:
            await Agent(model).run("?")
    return caught.value


@pytest.mark.parametrize(
    "provider", [OpenAIFormat(), AnthropicFormat()], ids=["openai", "anthropic"]
)
@pytest.mark.parametrize(
    ("kind", "code", "status"),
    [
        ("401", base.KEY_REJECTED, 401),
        # Timeweb на неверный ключ отвечает 403, Anthropic 401
        ("403", base.KEY_REJECTED, 403),
        ("402", base.NO_FUNDS, 402),
        ("404", base.MODEL_MISSING, 404),
        ("429", base.RATE_LIMITED, 429),
        ("500", base.SERVER, 500),
        ("timeout", base.TIMEOUT, None),
        ("connect", base.SERVER, None),
        # так Timeweb однажды оборвал запрос с инструментами
        ("disconnect", base.SERVER, None),
    ],
)
async def test_run_errors_get_our_codes(provider, kind, code, status):
    error = provider.error_from(await run_error(provider, kind))
    assert (error.code, error.http_status) == (code, status)


async def test_provider_overrides_status():
    # провайдер, у которого пустой баланс приходит как 400: перевод его, а не общий
    class Quirky(OpenAIFormat):
        def error_code(self, status):
            return base.NO_FUNDS if status == 400 else super().error_code(status)

    provider = Quirky()
    assert provider.error_from(await run_error(provider, "400")).code == base.NO_FUNDS


async def test_own_request_errors():
    # models() и check_key ходят сами через httpx2: таймаут и обрыв те же коды
    provider = OpenAIFormat()
    request = httpx2.Request("GET", "https://x.test/v1/models")
    assert provider.error_from(httpx2.ConnectTimeout("t", request=request)).code == base.TIMEOUT
    assert provider.error_from(httpx2.ReadError("r", request=request)).code == base.SERVER


def test_provider_error_passes_through():
    error = ProviderError(base.NO_FUNDS, 402)
    assert OpenAIFormat().error_from(error) is error


@pytest.mark.parametrize(
    "exc", [ValueError("x"), UnexpectedModelBehavior("ответ не по схеме")], ids=["value", "schema"]
)
def test_not_provider_errors(exc):
    # модель ответила не по схеме: это не поломка подключения, карточку не краснит
    assert OpenAIFormat().error_from(exc) is None


def test_provider_must_build_model():
    class Forgetful(Provider):
        kind = "forgetful"

        async def models(self, http, *, key, base_url):
            return []

    with pytest.raises(TypeError, match="model"):
        Forgetful()
