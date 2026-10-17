"""Общий родитель провайдеров на OpenAI-формате (chat/completions, /models).

Наследнику остаётся адрес и, если нужно, фильтр списка моделей: Timeweb,
OpenRouter, свой сервер владельца отличаются только этим.
"""

from typing import Any, ClassVar

import httpx2
from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.ai.providers.base import SERVER, ModelInfo, Provider, ProviderError


class OpenAICompatible(Provider):
    # адрес известного провайдера; пусто, если адрес вводит владелец
    default_url: ClassVar[str | None] = None

    def url(self, base_url: str | None) -> str:
        url = base_url or self.default_url
        if not url:
            # needs_base_url без адреса: сервис ai такое не сохранит, это ошибка в коде
            raise ValueError(f"{self.kind}: нужен адрес провайдера")
        return url.rstrip("/")

    def model(
        self, http: httpx2.AsyncClient, *, key: str, base_url: str | None, model_id: str
    ) -> Model:
        client = AsyncOpenAI(
            base_url=self.url(base_url), api_key=key, max_retries=0, http_client=http
        )
        return OpenAIChatModel(model_id, provider=OpenAIProvider(openai_client=client))

    async def models(
        self, http: httpx2.AsyncClient, *, key: str, base_url: str | None
    ) -> list[ModelInfo]:
        try:
            response = await http.get(
                f"{self.url(base_url)}/models", headers={"Authorization": f"Bearer {key}"}
            )
        except httpx2.TransportError as exc:
            raise self.error_from(exc) from exc
        if response.is_error:
            raise ProviderError(self.error_code(response.status_code), response.status_code)
        try:
            listed = response.json()["data"]
            return [ModelInfo(str(raw["id"])) for raw in listed if self.keep(raw)]
        except (ValueError, KeyError, TypeError) as exc:
            # 200, но не список моделей: прокси отдал свою страницу или формат другой
            raise ProviderError(SERVER, response.status_code) from exc

    def keep(self, raw: dict[str, Any]) -> bool:
        """Показывать ли модель владельцу. По умолчанию все: в /models OpenAI нет
        признака, текстовая ли модель."""
        return True
