"""Схемы HTTP: что ручки ai принимают и отдают. Модели наружу не отдаём."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

# пустое имя можно: сервис подставит имя провайдера
Name = Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)]
# короткий ключ отсекает сервис (KeyTooShort), здесь только предел от мусора:
# настоящие ключи короче сотни символов, а длинное тело ушло бы провайдеру
Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
# какие провайдеры есть, решает реестр (UnknownProvider), здесь только длина
ProviderKind = Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)]
BaseUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048)]


class ProviderOut(BaseModel):
    kind: str
    # провайдер без своего адреса: форма просит адрес у владельца
    needs_base_url: bool


class ConnectionIn(BaseModel):
    provider: ProviderKind
    name: Name = ""
    key: Key
    # только у провайдера без своего адреса, у остальных BaseUrlNotAllowed
    base_url: BaseUrl | None = None


class KeyIn(BaseModel):
    key: Key


class NameIn(BaseModel):
    name: Name


class TaskOut(BaseModel):
    """Задача на подключении: «Ассистент: ответ · 2 аккаунта · 2 модели»."""

    purpose: str
    # сколько настроек задачи идут через это подключение (общая и по аккаунтам)
    scopes: int
    models: list[str]
    # провайдер сказал, что модели нет: владелец выбирает другую в самой задаче
    model_missing: bool


class ConnectionOut(BaseModel):
    """Ключа здесь нет и не будет, только последние символы."""

    id: uuid.UUID
    provider: str
    name: str
    key_hint: str
    base_url: str | None
    # «проверен»: последний итог про этот ключ успешный
    checked_at: datetime | None
    # поломка, которая сама не пройдёт: key_rejected, no_funds, key_unreadable
    error_code: str | None
    error_at: datetime | None
    created_at: datetime
    tasks: list[TaskOut]


class CheckedOut(BaseModel):
    """Карточка и итог только что сделанной проверки. Итог отдельно: разовый сбой
    (timeout, server, rate_limited) карточку не меняет, а человеку нужно знать,
    что проверка не прошла."""

    connection: ConnectionOut
    # "ok" или код ошибки проверки
    check: str
