"""Anthropic напрямую: свой протокол (messages), кэш базы знаний и строгий JSON.

Формат не OpenAI, поэтому наследник Provider, а не OpenAICompatible: и сборка
модели, и список моделей свои. Ключ идёт в x-api-key, а не в Authorization.

Серверные инструменты Anthropic (веб-поиск, выполнение кода) не включать без
счётчика на уровне HTTP: с ними сервер отвечает pause_turn, SDK сам шлёт
продолжения внутри одного шага, и журнал с пределом шагов их не видят.
"""

from typing import Any

import httpx2
from anthropic import AsyncAnthropic
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider as PydanticAnthropicProvider

from app.ai.providers.base import MODEL_MISSING, SERVER, ModelInfo, Provider, ProviderError

API = "https://api.anthropic.com"
# версия протокола в заголовке, без неё Anthropic не отвечает
VERSION = "2023-06-01"
# страница списка моделей: максимум, который принимает Anthropic
PAGE = 1000
# сломанный has_more не уведёт в вечный цикл: моделей у Anthropic десятки
MAX_PAGES = 10


class AnthropicProvider(Provider):
    kind = "anthropic"

    def error_from(self, exc: BaseException) -> ProviderError | None:
        # 403 permission_error на вызове модели: у ключа нет прав на эту модель
        # (закрыта для workspace). Ключ рабочий: помечаем задачу, а не карточку,
        # иначе она мигала бы от других задач на этом же ключе. На списке моделей
        # (проверка ключа) 403 остаётся «ключ не принят»: такой ключ ни на что не годен
        if isinstance(exc, ModelHTTPError) and exc.status_code == 403:
            return ProviderError(MODEL_MISSING, 403)
        return super().error_from(exc)

    def url(self, base_url: str | None) -> str:
        return (base_url or API).rstrip("/")

    def model(
        self, http: httpx2.AsyncClient, *, key: str, base_url: str | None, model_id: str
    ) -> Model:
        client = AsyncAnthropic(
            api_key=key, base_url=self.url(base_url), max_retries=0, http_client=http
        )
        return AnthropicModel(model_id, provider=PydanticAnthropicProvider(anthropic_client=client))

    async def models(
        self, http: httpx2.AsyncClient, *, key: str, base_url: str | None
    ) -> list[ModelInfo]:
        headers = {"x-api-key": key, "anthropic-version": VERSION}
        listed: list[ModelInfo] = []
        after: str | None = None
        for _ in range(MAX_PAGES):
            params = {"limit": PAGE} | ({"after_id": after} if after else {})
            body = await self.get_json(
                http, f"{self.url(base_url)}/v1/models", headers=headers, params=params
            )
            try:
                listed += [_info(raw) for raw in body["data"]]
                if not body.get("has_more"):
                    return listed
                after = str(body["last_id"])
            except (KeyError, TypeError) as exc:
                raise ProviderError(SERVER, 200) from exc
        raise ProviderError(SERVER, 200)


def _info(raw: dict[str, Any]) -> ModelInfo:
    # возможности приходят у каждой модели: строгий JSON берём, остальное пока не нужно
    strict = (raw.get("capabilities") or {}).get("structured_outputs") or {}
    supported = strict.get("supported")
    return ModelInfo(
        str(raw["id"]),
        raw.get("display_name"),
        supported if isinstance(supported, bool) else None,
    )
