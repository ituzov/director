"""Автоответы: кодовое слово под постом -> ответ в комментах и Private Reply,
проверка подписки, второй шаг по кнопке.

Верхний модуль: использует instagram и identity.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.autoreplies.service import handle_comment

__all__ = [
    # обработчики для worker
    "handle_comment",
]
