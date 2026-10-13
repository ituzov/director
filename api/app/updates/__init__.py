"""Обновления: какие версии вышли (versions.json на opendirector.dev) и что
предложить этой установке.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.updates.routes import router

__all__ = [
    # HTTP модуля, подключает main
    "router",
]
