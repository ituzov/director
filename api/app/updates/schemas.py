"""Схемы HTTP: что отдаёт ручка updates. Повторяют справки service, без логики."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


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
