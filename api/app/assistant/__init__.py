"""Ассистент: отвечает на комменты, которые не взял ни один автоответ, по
инструкции и базе знаний владельца. Модель зовёт через ai, отвечает через
очередь исходящих instagram.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.assistant.exceptions import AssistantError
from app.assistant.routes import assistant_error_handler, router
from app.assistant.tasks import Taken, handle_comment

__all__ = [
    # HTTP: экран ассистентов аккаунта
    "router",
    "assistant_error_handler",
    "AssistantError",
    # задачи worker
    "handle_comment",
    "Taken",
]
