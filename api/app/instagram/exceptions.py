"""Ошибки instagram. Ручки превращают их в HTTP-коды, сервисы про HTTP не знают."""


class InstagramError(Exception):
    """Общий предок: ручке удобно ловить все ошибки модуля разом."""


class AppSecretRequired(InstagramError):
    """Приложение Meta сохраняют впервые, а секрета нет."""


class MetaAppRequired(InstagramError):
    """Подключать аккаунты можно только после ключей приложения Meta."""


class PublicUrlRequired(InstagramError):
    """Без PUBLIC_URL нет адреса возврата: Instagram некуда вернуть человека."""


class InvalidOAuthState(InstagramError):
    """Пропуск входа не наш, просрочен или выдан другому пользователю."""


class OAuthFailed(InstagramError):
    """Meta ответила ошибкой на одном из шагов подключения."""


class AccountNotFound(InstagramError):
    """Такого аккаунта в установке нет."""


class AccountUnavailable(InstagramError):
    """Аккаунта нет, он отключён или его токен больше не годен."""


class MetaUnavailable(InstagramError):
    """Meta не ответила или ответила ошибкой, которую повтор может исправить."""
