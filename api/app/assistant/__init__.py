"""Ассистент: отвечает на комменты, которые не взял ни один автоответ, по
инструкции и базе знаний владельца. Модель зовёт через ai, отвечает через
очередь исходящих instagram.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.assistant.exceptions import AssistantError
from app.assistant.routes import assistant_error_handler, router

__all__ = [
    # HTTP: экран ассистентов аккаунта
    "router",
    "assistant_error_handler",
    "AssistantError",
]
