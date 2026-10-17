"""Что должен уметь провайдер моделей, чтобы Директор с ним работал.

Провайдер это профиль, а не подключение: один объект на всех, ключ и адрес
приходят в каждом вызове из ai.connection. Он собирает модель Pydantic AI,
проверяет ключ, отдаёт список моделей и переводит свои ошибки в наши коды.
О базе, журнале и карточке подключения не знает, это делает сервис ai.

Новый провайдер: наследник Provider (или OpenAICompatible для OpenAI-формата)
и строка в реестре. Как добавить: docs/development/ai-providers.md.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx2
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models import Model

# наши коды ошибок: по ним сервис решает, краснить ли карточку подключения
KEY_REJECTED = "key_rejected"
NO_FUNDS = "no_funds"
MODEL_MISSING = "model_missing"
RATE_LIMITED = "rate_limited"
TIMEOUT = "timeout"
SERVER = "server"
# ответил, но не тем: пустой ответ, чужой формат. Токены могли списать
BAD_RESPONSE = "bad_response"


class ProviderError(Exception):
    """Провайдер ответил ошибкой или не ответил. Текст ответа не храним:
    провайдеры кладут в него куски запроса, а там комменты людей."""

    def __init__(self, code: str, http_status: int | None = None) -> None:
        super().__init__(f"провайдер: {code} (HTTP {http_status})")
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class ModelInfo:
    # как у провайдера: claude-haiku-5-5, anthropic/claude-haiku-5-5
    id: str
    # для людей, если провайдер отдаёт; иначе экран покажет id
    name: str | None = None
    # схему ответа соблюдает сам провайдер (NativeOutput); None: не знаем, идём
    # через инструмент, как у всех
    strict_json: bool | None = None


def error_code(status: int) -> str:
    """Общее правило перевода HTTP-статуса. Провайдер уточняет у себя, если
    отвечает не по нему (например, пустой баланс не 402)."""
    if status in (401, 403):
        return KEY_REJECTED
    if status == 402:
        return NO_FUNDS
    if status == 404:
        return MODEL_MISSING
    if status == 429:
        return RATE_LIMITED
    return SERVER


def _is_timeout(exc: BaseException) -> bool:
    # SDK заворачивает таймаут httpx2 в свои ошибки, а Pydantic AI ещё раз в
    # ModelAPIError: отличить таймаут от обрыва можно только по причине внутри
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, httpx2.TimeoutException):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


class Provider(ABC):
    # ключ реестра и значение ai.connection.provider
    kind: ClassVar[str]
    # адрес вводит владелец (свой OpenAI-совместимый сервер)
    needs_base_url: ClassVar[bool] = False

    @abstractmethod
    def model(
        self, http: httpx2.AsyncClient, *, key: str, base_url: str | None, model_id: str
    ) -> Model:
        """Модель Pydantic AI поверх нашего клиента. В сеть не ходит. SDK
        собирается без своих повторов: каждый запрос должен попасть в журнал,
        а повторять или нет, решает тот, кто зовёт ai.run."""

    @abstractmethod
    async def models(
        self, http: httpx2.AsyncClient, *, key: str, base_url: str | None
    ) -> list[ModelInfo]:
        """Модели для текста, без картинок, речи и эмбеддингов. Бросает ProviderError."""

    async def check_key(self, http: httpx2.AsyncClient, *, key: str, base_url: str | None) -> None:
        """Ключ и адрес рабочие. По умолчанию список моделей: он бесплатный."""
        await self.models(http, key=key, base_url=base_url)

    def error_code(self, status: int) -> str:
        """Наш код по HTTP-статусу провайдера."""
        return error_code(status)

    async def get_json(
        self,
        http: httpx2.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Свой запрос к провайдеру мимо SDK (список моделей): ошибки нашими кодами.
        Сначала самая точная причина: не дошёл, ответил ошибкой, ответил не JSON."""
        try:
            response = await http.get(url, headers=headers, params=params)
        except httpx2.TransportError as exc:
            raise self.error_from(exc) from exc
        if response.is_error:
            raise ProviderError(self.error_code(response.status_code), response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            # 200, но не JSON: прокси отдал свою страницу
            raise ProviderError(SERVER, response.status_code) from exc

    def error_from(self, exc: BaseException) -> ProviderError | None:
        """Ошибка запроса к провайдеру нашим кодом: ответ со статусом из
        agent.run, таймаут или обрыв. None, если это не ошибка провайдера:
        например, модель дважды ответила не по схеме, это решает сервис ai."""
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, ModelHTTPError):
            return ProviderError(self.error_code(exc.status_code), exc.status_code)
        if isinstance(exc, ModelAPIError | httpx2.TransportError):
            return ProviderError(TIMEOUT if _is_timeout(exc) else SERVER)
        return None
