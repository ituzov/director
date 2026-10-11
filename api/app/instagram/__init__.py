"""Подключённые аккаунты Instagram: OAuth, токены и их обновление,
клиент Graph API, приём webhook во входящие.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.instagram.contracts import CommentRef, InboxHandlers
from app.instagram.exceptions import InstagramError
from app.instagram.routes import instagram_error_handler, router, webhook_router
from app.instagram.tasks import process_inbox_event

__all__ = [
    # HTTP модуля, подключает main
    "InstagramError",
    "instagram_error_handler",
    "router",
    "webhook_router",
    # задачи worker
    "process_inbox_event",
    "InboxHandlers",
    "CommentRef",
]
