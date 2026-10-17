"""Справки ai для соседей: frozen dataclass вместо записей из базы."""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BindingRef:
    """Через какое подключение и модель идёт задача в одной области."""

    scope: str | None
    # None: подключение удалили, задача «не настроена»
    connection_id: uuid.UUID | None
    model: str
    # провайдер сказал, что такой модели нет: владелец выбирает другую
    model_missing: bool
