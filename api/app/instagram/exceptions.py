"""Ошибки instagram. Ручки превращают их в HTTP-коды, сервисы про HTTP не знают."""


class InstagramError(Exception):
    """Общий предок: ручке удобно ловить все ошибки модуля разом."""


class AppSecretRequired(InstagramError):
    """Приложение Meta сохраняют впервые, а секрета нет."""
