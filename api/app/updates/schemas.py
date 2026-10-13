"""Схемы HTTP: что отдаёт ручка updates. Повторяют справки service, без логики."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    # собираются из frozen dataclass сервиса по атрибутам
    model_config = ConfigDict(from_attributes=True)


class TextOut(_Out):
    ru: str
    en: str


class ReleaseOut(_Out):
    version: str
    date: str
    notes: TextOut
    important: TextOut | None
    breaking: bool
    security: bool


class AvailableOut(_Out):
    latest: str | None
    releases: list[ReleaseOut]
    blocked: Literal["dev", "channel", "min_from"] | None
    min_from: str | None


class UpdatesOut(_Out):
    current: str
    channel: str
    available: AvailableOut | None
    message: TextOut | None
    error: Literal["unreachable", "invalid"] | None


class UpdateIn(BaseModel):
    # формат сверяет сервис: версия должна совпасть с последней доступной
    version: str = Field(min_length=1, max_length=64)


class StatusOut(_Out):
    phase: Literal["idle", "queued", "stuck", "running", "done", "failed"]
    step: str | None
    at: datetime | None
    log: list[str]
