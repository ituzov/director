"""Вызов модели для задачи: ai.run.

Находит, через какое подключение и модель идёт задача, собирает модель,
запускает агента и пишет каждый запрос к провайдеру строкой в журнал ai.call.
Ошибки нашими кодами, поломка подключения на карточку.

Сессии свои и короткие, сессию сюда не передают (исключение записано в
docs/development/modules.md): ответ модели идёт секунды, его нельзя ждать под
чужой транзакцией, а строка журнала это потраченные деньги и не должна
откатиться вместе с вызывающим.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anyio
import httpx2
import structlog
from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage, UsageLimits
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import providers, repository
from app.ai.exceptions import AiCallFailed
from app.ai.providers.base import BAD_RESPONSE, MODEL_MISSING, Provider, ProviderError
from app.ai.service import KEY_UNREADABLE, apply_result
from app.core import crypto
from app.db import SessionLocal

log = structlog.get_logger("app.ai")

NOT_CONFIGURED = "not_configured"
STEP_LIMIT = "step_limit"
# запрос оборвал вызывающий: в журнале есть, карточку не трогает
CANCELLED = "cancelled"
BAD_OUTPUT = "bad_output"

# шагов в одном запуске: запросы к модели и переспросы по схеме вместе
STEPS = 5
# ответ модели пишется долго, но не бесконечно
CALL_TIMEOUT = 120.0

MakeSession = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _http() -> httpx2.AsyncClient:
    # один клиент на запуск; тесты подменяют эту функцию
    return httpx2.AsyncClient(timeout=CALL_TIMEOUT)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Using:
    """Подключение и модель явно, мимо настройки задачи. Для песочницы: она
    проверяет поля, которые владелец ещё не сохранил."""

    connection_id: uuid.UUID
    model: str


@dataclass(frozen=True, slots=True)
class _Target:
    """Что прочитали из настроек до сети: дальше в базу не ходим до ответа."""

    purpose: str
    scope: str | None
    connection_id: uuid.UUID
    provider: Provider
    model: str
    key: str
    base_url: str | None
    # отпечаток ключа: итог вызова ложится на карточку, только если ключ тот же
    key_changed_at: datetime
    # вызов по настройке задачи, а не по Using: только тогда 404 её помечает
    by_binding: bool = True


async def run(
    *,
    purpose: str,
    scope: str | None,
    agent: Agent[Any, Any],
    prompt: str | None,
    deps: Any = None,
    conversation: Any = None,
    steps: int = STEPS,
    using: Using | None = None,
    make_session: MakeSession = SessionLocal,
) -> AgentRunResult[Any]:
    """Запустить агента задачи через её подключение и модель. Зовут вне своей
    транзакции. Ответа нет: AiCallFailed с кодом, вызывающий молчит.

    using: подключение и модель явно, настройка задачи не читается. Журнал пишется
    с этими purpose и scope как обычно, а 404 «модели нет» настройку не помечает:
    пометка ставится, только если вызов шёл по ней."""
    target = await _target(make_session, purpose, scope, using)
    async with _http() as http:
        model = _Journaled(
            target.provider.model(
                http, key=target.key, base_url=target.base_url, model_id=target.model
            ),
            target,
            make_session,
        )
        try:
            return await agent.run(
                prompt,
                model=model,
                deps=deps,
                conversation=conversation,
                usage_limits=UsageLimits(request_limit=steps + _spent(conversation)),
            )
        # from None: в цепочке исключений Pydantic AI лежит тело ответа провайдера,
        # а там бывают куски запроса. Код и статус и так в журнале
        except ProviderError as error:
            raise AiCallFailed(error.code) from None
        except UsageLimitExceeded:
            log.warning("ai.call.step_limit", purpose=purpose, steps=steps)
            raise AiCallFailed(STEP_LIMIT) from None
        except UnexpectedModelBehavior:
            # модель упорно отвечает не по схеме: подключение тут ни при чём
            log.warning("ai.call.bad_output", purpose=purpose, model=target.model)
            raise AiCallFailed(BAD_OUTPUT) from None
        # остальное летит как есть: это ошибка в инструменте вызывающего, а не
        # сбой провайдера, прятать её под AiCallFailed нельзя


async def _unreadable(
    session: AsyncSession, connection_id: uuid.UUID, key_changed_at: datetime
) -> None:
    """Ключ не расшифровать: на карточку, но только про этот ключ. Читали без
    замка: перечитываем под замком и сверяем отпечаток, иначе замена ключа,
    успевшая между чтением и записью, получила бы «не расшифровать»."""
    connection = await repository.get_connection(session, connection_id, lock=True)
    if connection is None:
        raise AiCallFailed(NOT_CONFIGURED)
    apply_result(connection, key_changed_at=key_changed_at, started=_now(), code=KEY_UNREADABLE)
    await session.commit()
    log.warning("ai.connection.key_unreadable", connection_id=str(connection_id))


def _spent(conversation: Any) -> int:
    """Запросы, которые разговор принёс из прошлых ответов. Pydantic AI считает
    предел по счётчику разговора, а не запуска: без поправки шестое сообщение
    человека упёрлось бы в предел ещё до запроса к модели."""
    usage = getattr(conversation, "usage", None)
    return usage.requests if usage is not None else 0


async def _target(
    make_session: MakeSession, purpose: str, scope: str | None, using: Using | None = None
) -> _Target:
    async with make_session() as session:
        if using is None:
            binding = await repository.get_binding(session, purpose=purpose, scope=scope)
            if binding is None or binding.connection_id is None:
                raise AiCallFailed(NOT_CONFIGURED)
            if binding.model_missing_at is not None:
                # владелец должен выбрать другую модель: эту провайдер уже не знает
                raise AiCallFailed(MODEL_MISSING)
            connection_id, model = binding.connection_id, binding.model
        else:
            connection_id, model = using.connection_id, using.model.strip()
            if not model:
                raise AiCallFailed(NOT_CONFIGURED)
        connection = await repository.get_connection(session, connection_id)
        provider = providers.get(connection.provider) if connection else None
        if connection is None or provider is None:
            raise AiCallFailed(NOT_CONFIGURED)
        try:
            key = crypto.decrypt(connection.key_encrypted)
        except crypto.DecryptError:
            await _unreadable(session, connection.id, connection.key_changed_at)
            raise AiCallFailed(KEY_UNREADABLE) from None
        return _Target(
            purpose,
            scope,
            connection.id,
            provider,
            model,
            key,
            connection.base_url,
            connection.key_changed_at,
            by_binding=using is None,
        )


class _Journaled(WrapperModel):
    """Модель, которая пишет каждый запрос к провайдеру в журнал: и обычный, и
    потоковый, и упавший. Переспрос по схеме и шаг с инструментом тоже запросы."""

    def __init__(self, wrapped, target: _Target, make_session: MakeSession) -> None:
        super().__init__(wrapped)
        self.target = target
        self.make_session = make_session

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        started, clock = _now(), time.monotonic()
        try:
            response = await super().request(messages, model_settings, model_request_parameters)
        except asyncio.CancelledError:
            await self._cancelled(started, clock)
            raise
        except Exception as exc:
            raise await self._failed(exc, started, clock) from None
        await self._record(started, clock, response.usage, None)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncIterator[StreamedResponse]:
        started, clock = _now(), time.monotonic()
        try:
            async with super().request_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as stream:
                yield stream
        except asyncio.CancelledError:
            await self._cancelled(started, clock)
            raise
        except Exception as exc:
            raise await self._failed(exc, started, clock) from None
        await self._record(started, clock, stream.usage, None)

    async def _cancelled(self, started: datetime, clock: float) -> None:
        """Запрос оборвал вызывающий (свой таймаут, остановка worker). Токены могли
        уже списать: строка в журнал всё равно."""
        await self._record(started, clock, None, ProviderError(CANCELLED))

    async def _record(
        self,
        started: datetime,
        clock: float,
        usage: RequestUsage | None,
        error: ProviderError | None,
    ) -> None:
        """Любая запись итога под защитой от отмены: ответ уже получен и, может быть,
        оплачен, а запись ждёт соединение или замок строки. Pydantic AI работает на
        anyio, там отмена повторяется на каждом await, asyncio.shield её не удержит."""
        with anyio.CancelScope(shield=True):
            await _record(self.make_session, self.target, started, clock, usage, error)

    async def _failed(self, exc: BaseException, started: datetime, clock: float) -> ProviderError:
        """Любая ошибка запроса к модели: строка в журнал и наш код. Неопознанное
        (пустой ответ, чужой формат) это bad_response: токены могли списать, и
        предохранитель должен этот вызов увидеть."""
        error = self.target.provider.error_from(exc) or ProviderError(BAD_RESPONSE)
        await self._record(started, clock, None, error)
        return error


async def _record(
    make_session: MakeSession,
    target: _Target,
    started: datetime,
    clock: float,
    usage: RequestUsage | None,
    error: ProviderError | None,
) -> None:
    """Строка журнала и итог на карточку подключения, отдельной транзакцией.
    Карточку двигает только итог про текущий ключ, свежее записанного."""
    async with make_session() as session:
        connection = await repository.get_connection(session, target.connection_id, lock=True)
        repository.add_call(
            session,
            started_at=started,
            duration_ms=round((time.monotonic() - clock) * 1000),
            purpose=target.purpose,
            scope=target.scope,
            # подключение удалили, пока шёл вызов: строка остаётся без ссылки
            connection_id=connection.id if connection else None,
            provider=target.provider.kind,
            model=target.model,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cached_tokens=usage.cache_read_tokens if usage else None,
            outcome="error" if error else "ok",
            error_code=error.code if error else None,
            http_status=error.http_status if error else None,
        )
        if connection is not None:
            apply_result(
                connection,
                key_changed_at=target.key_changed_at,
                started=started,
                code=error.code if error else None,
            )
        if (
            error is not None
            and error.code == MODEL_MISSING
            and connection is not None
            and target.by_binding
        ):
            await _model_missing(session, target, connection)
        await session.commit()
    if error is not None:
        log.warning(
            "ai.call.failed",
            purpose=target.purpose,
            provider=target.provider.kind,
            model=target.model,
            code=error.code,
            http_status=error.http_status,
        )


async def _model_missing(session: AsyncSession, target: _Target, connection) -> None:
    """404 по модели помечает настройку задачи, только если это та же настройка,
    с которой шёл вызов: та же модель, то же подключение, тот же ключ. Иначе
    пометка заблокировала бы новую настройку, которую 404 не касался."""
    binding = await repository.get_binding(
        session, purpose=target.purpose, scope=target.scope, lock=True
    )
    if (
        binding is not None
        and binding.model == target.model
        and binding.connection_id == target.connection_id
        and connection.key_changed_at == target.key_changed_at
    ):
        binding.model_missing_at = _now()
