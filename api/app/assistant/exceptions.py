"""Ошибки assistant. Ручки превращают их в HTTP-коды, сервисы про HTTP не знают."""

import uuid


class AssistantError(Exception):
    """Общий предок: ручке удобно ловить все ошибки модуля разом."""


class AssistantNotFound(AssistantError):
    """Такого ассистента нет."""


class AssistantArchived(AssistantError):
    """Архивного не правят и не включают: сначала вернуть из архива."""


class AccountUnavailable(AssistantError):
    """Аккаунта нет или он отключён: ассистенту некуда отвечать."""


class ConnectionMissing(AssistantError):
    """Выбранного подключения к нейросети нет: удалили в другой вкладке."""


class AssistantConflict(AssistantError):
    """Место занято другим живым ассистентом: общий у аккаунта один, пост у
    одного частного. На паузе тоже занимает, архивный нет."""

    def __init__(
        self,
        kind: str,
        *,
        value: str | None,
        assistant_id: uuid.UUID,
        name: str,
        enabled: bool,
    ) -> None:
        super().__init__(kind)
        # general: общий уже есть; post: пост у другого частного
        self.kind = kind
        # id поста или None для общего
        self.value = value
        # кем занято: форма покажет «уже у «Все вопросы» (на паузе)»
        self.assistant_id = assistant_id
        self.name = name
        self.enabled = enabled
