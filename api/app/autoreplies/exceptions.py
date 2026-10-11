"""Ошибки autoreplies. Ручки превращают их в HTTP-коды, сервисы про HTTP не знают."""

import uuid


class AutoreplyError(Exception):
    """Общий предок: ручке удобно ловить все ошибки модуля разом."""


class AutoreplyNotFound(AutoreplyError):
    """Такого автоответа нет."""


class AccountUnavailable(AutoreplyError):
    """Аккаунта нет или он отключён: автоответу некуда отвечать."""


class AutoreplyConflict(AutoreplyError):
    """Слово уже у другого общего или пост уже у другого частного автоответа."""

    def __init__(
        self,
        kind: str,
        *,
        value: str,
        autoreply_id: uuid.UUID,
        name: str,
        enabled: bool,
    ) -> None:
        super().__init__(kind)
        # keyword или post: что именно занято
        self.kind = kind
        # само слово (как ввёл владелец) или id поста
        self.value = value
        # кем занято: форма покажет «уже есть „Гайд“ (выключен)»
        self.autoreply_id = autoreply_id
        self.name = name
        self.enabled = enabled
