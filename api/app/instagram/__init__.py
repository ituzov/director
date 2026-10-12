"""Подключённые аккаунты Instagram: OAuth, токены и их обновление,
клиент Graph API, приём webhook во входящие.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.instagram.contracts import (
    AccountRef,
    Button,
    CommentRef,
    InboxHandlers,
    OutboxResult,
    PostbackRef,
)
from app.instagram.exceptions import InstagramError
from app.instagram.outbox import (
    FOLLOWING,
    NOT_FOLLOWING,
    UNKNOWN,
    enqueue_comment_reply,
    enqueue_message,
    enqueue_private_reply,
)
from app.instagram.routes import instagram_error_handler, router, webhook_router
from app.instagram.service import count_undelivered, get_account
from app.instagram.tasks import process_inbox_event, refresh_due_tokens, send_outbox_task

__all__ = [
    # HTTP модуля, подключает main
    "InstagramError",
    "instagram_error_handler",
    "router",
    "webhook_router",
    # для соседей
    "AccountRef",
    "get_account",
    "count_undelivered",
    # исходящие: соседи ставят в своей транзакции, отправляет worker
    "Button",
    "enqueue_comment_reply",
    "enqueue_message",
    "enqueue_private_reply",
    # варианты сообщения с проверкой подписки
    "FOLLOWING",
    "NOT_FOLLOWING",
    "UNKNOWN",
    # задачи worker
    "process_inbox_event",
    "InboxHandlers",
    "CommentRef",
    "PostbackRef",
    "send_outbox_task",
    "OutboxResult",
    "refresh_due_tokens",
]
