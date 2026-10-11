"""Пользователи и доступ: владелец, участники, приглашения, роли в аккаунтах.

Публичный интерфейс модуля: снаружи импортируют только отсюда.
"""

from app.identity.contracts import UserRef
from app.identity.deps import CanConnectAccounts, CurrentOwner, CurrentUserRef
from app.identity.exceptions import IdentityError
from app.identity.routes import identity_error_handler, router

__all__ = [
    # для ручек соседей: кто делает запрос и проверки доступа
    "CanConnectAccounts",
    "CurrentOwner",
    "CurrentUserRef",
    # справки
    "UserRef",
    # HTTP модуля, подключает main
    "IdentityError",
    "identity_error_handler",
    "router",
]
