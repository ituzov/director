"""Ошибки identity. Ручки превращают их в HTTP-коды, сервисы про HTTP не знают."""


class IdentityError(Exception):
    """Общий предок: ручке удобно ловить все ошибки модуля разом."""


class SetupDisabled(IdentityError):
    """SETUP_TOKEN не задан: регистрация владельца выключена."""


class InvalidSetupToken(IdentityError):
    """Токен не совпал."""


class OwnerAlreadyExists(IdentityError):
    """Владелец уже есть, setup больше не нужен."""


class WeakPassword(IdentityError):
    """Пароль короче минимума."""


class InvalidCredentials(IdentityError):
    """Нет такой почты или пароль не подошёл. Нарочно одна ошибка на оба случая."""


class OwnerOnly(IdentityError):
    """Действие только для владельца установки."""
