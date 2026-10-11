"""Автоответы: кодовое слово под постом -> ответ в комментах и Private Reply,
проверка подписки, второй шаг по кнопке.

Верхний модуль: использует instagram и identity.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.autoreplies.exceptions import AutoreplyError
from app.autoreplies.routes import autoreply_error_handler, router
from app.autoreplies.service import handle_comment, handle_postback, handle_send_result

__all__ = [
    # HTTP модуля, подключает main
    "AutoreplyError",
    "autoreply_error_handler",
    "router",
    # обработчики для worker
    "handle_comment",
    "handle_postback",
    "handle_send_result",
]
