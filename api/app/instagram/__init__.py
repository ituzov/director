"""Подключённые аккаунты Instagram: OAuth, токены и их обновление,
клиент Graph API, приём webhook во входящие.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.instagram.contracts import AccountRef, CommentRef, InboxHandlers
from app.instagram.exceptions import InstagramError
from app.instagram.routes import instagram_error_handler, router, webhook_router
from app.instagram.service import get_account
from app.instagram.tasks import process_inbox_event

__all__ = [
    # HTTP модуля, подключает main
    "InstagramError",
    "instagram_error_handler",
    "router",
    "webhook_router",
    # для соседей
    "AccountRef",
    "get_account",
    # задачи worker
    "process_inbox_event",
    "InboxHandlers",
    "CommentRef",
]
