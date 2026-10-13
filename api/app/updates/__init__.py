"""Обновления: какие версии вышли (versions.json на opendirector.dev), что
предложить этой установке, просьба хосту обновиться и её ход.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.updates.exceptions import UpdatesError
from app.updates.routes import router, updates_error_handler

__all__ = [
    # HTTP модуля, подключает main
    "UpdatesError",
    "router",
    "updates_error_handler",
]
