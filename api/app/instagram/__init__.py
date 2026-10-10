"""Подключённые аккаунты Instagram: OAuth, токены и их обновление,
клиент Graph API, приём webhook во входящие.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.instagram.exceptions import InstagramError
from app.instagram.routes import instagram_error_handler, router

__all__ = [
    # HTTP модуля, подключает main
    "InstagramError",
    "instagram_error_handler",
    "router",
]
