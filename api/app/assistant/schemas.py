"""Схемы HTTP: что ручки assistant принимают и отдают. Модели наружу не отдаём."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

# база знаний целиком уходит в каждый запрос: 50 000 символов это ~15–20 тысяч
# токенов, дальше пора искать по документам, а не класть всё
MAX_KNOWLEDGE = 50_000
MAX_INSTRUCTION = 5_000


def _text(max_length: int, min_length: int = 0) -> StringConstraints:
    return StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)


Name = Annotated[str, _text(100, 1)]
MediaId = Annotated[str, _text(100, 1)]
Model = Annotated[str, _text(200, 1)]


class AssistantForm(BaseModel):
    name: Name
    scope: Literal["all", "posts"]
    media_ids: list[MediaId] = Field(default=[], max_length=50)
    mode: Literal["direct", "comment", "combo"]
    instruction: Annotated[str, _text(MAX_INSTRUCTION)] = ""
    knowledge: Annotated[str, _text(MAX_KNOWLEDGE)] = ""
    daily_limit: int = Field(ge=1, le=10_000)
    # через что отвечает: сохраняется в ai.binding вместе с формой
    connection_id: uuid.UUID
    model: Model

    @model_validator(mode="after")
    def _posts_match_scope(self) -> Self:
        # общий на всех постах, частный без постов ни на что бы не отвечал
        if self.scope == "all" and self.media_ids:
            raise ValueError("у общего ассистента нет своих постов")
        if self.scope == "posts" and not self.media_ids:
            raise ValueError("выберите хотя бы один пост")
        self.media_ids = sorted(set(self.media_ids))
        return self


class AssistantIn(AssistantForm):
    # при создании: чей ассистент. При правке аккаунт не меняется
    account_id: uuid.UUID


class EnabledIn(BaseModel):
    enabled: bool


class TodayOut(BaseModel):
    """Что ассистент сделал с комментами за сутки UTC."""

    answered: int
    unsure: int
    not_mine: int


class AssistantOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    name: str
    scope: str
    media_ids: list[str]
    mode: str
    instruction: str
    knowledge: str
    daily_limit: int
    enabled: bool
    archived_at: datetime | None
    # None: подключение удалили, ассистент молчит, пока не выберут другое
    connection_id: uuid.UUID | None
    model: str | None
    # провайдер сказал, что модели нет: выбрать другую
    model_missing: bool
    today: TodayOut
    updated_at: datetime


class TryIn(BaseModel):
    """Песочница: поля формы, от которых зависит ответ, даже несохранённые, и
    коммент. Ничего не отправляется и в предел ассистента не идёт."""

    # правят существующего: в журнале вызовов видно, на кого потрачены проверки
    assistant_id: uuid.UUID | None = None
    mode: Literal["direct", "comment", "combo"]
    instruction: Annotated[str, _text(MAX_INSTRUCTION)] = ""
    knowledge: Annotated[str, _text(MAX_KNOWLEDGE)] = ""
    connection_id: uuid.UUID
    model: Model
    # предел коммента в Instagram
    comment: Annotated[str, _text(2200, 1)]


class TryOut(BaseModel):
    """Как ответил бы ассистент. error: нейросеть не ответила (код ai), остальное пусто."""

    decision: Literal["answer", "unsure", "not_mine"] | None
    comment: str | None
    direct: str | None
    source: str | None
    error: str | None
