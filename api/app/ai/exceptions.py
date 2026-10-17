"""Ошибки ai. Ручки превращают их в HTTP-коды, сервисы про HTTP не знают."""


class AiError(Exception):
    """Общий предок: ручке удобно ловить все ошибки модуля разом."""


class UnknownProvider(AiError):
    """Такого провайдера в реестре нет."""


class BaseUrlRequired(AiError):
    """Провайдер со своим адресом, а адреса нет."""


class BaseUrlNotAllowed(AiError):
    """Адрес у известного провайдера: на этот адрес ушёл бы его ключ."""


class KeyTooShort(AiError):
    """Ключ короче настоящих: последние символы на экране выдали бы слишком много."""


class KeyRejected(AiError):
    """Провайдер не принял ключ при проверке: такой не сохраняем, он не заработает."""


class ConnectionNotFound(AiError):
    """Такого подключения нет: удалили или не было."""


class AiCallFailed(AiError):
    """Ответа модели нет. code говорит почему: not_configured, model_missing,
    key_unreadable, step_limit, bad_output или код провайдера (key_rejected,
    no_funds, rate_limited, timeout, server). Тот, кто звал, просто молчит."""

    def __init__(self, code: str) -> None:
        super().__init__(f"вызов модели не удался: {code}")
        self.code = code
