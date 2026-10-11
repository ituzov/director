"""Зависимости identity для ручек: кто делает запрос."""

from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import SessionDep
from app.identity import service
from app.identity.contracts import UserRef
from app.identity.exceptions import CannotConnectAccounts, OwnerOnly
from app.identity.models import User

# Нет заголовка Authorization: Bearer ... HTTPBearer сам ответит 401
_bearer = HTTPBearer()

BearerToken = Annotated[HTTPAuthorizationCredentials, Depends(_bearer)]


async def get_current_user(request: Request, session: SessionDep, credentials: BearerToken) -> User:
    user = await service.user_by_token(session, credentials.credentials)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Сессия недействительна",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # все записи лога ниже по запросу, в любом модуле, понесут user_id,
    # а строка запроса возьмёт его из request.state
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    request.state.log_context = {"user_id": str(user.id)}
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_user_ref(user: CurrentUser) -> UserRef:
    return UserRef(id=user.id, role=user.role, can_connect_accounts=user.can_connect_accounts)


# для соседей: кто делает запрос, справкой
CurrentUserRef = Annotated[UserRef, Depends(get_current_user_ref)]


async def require_owner(user: CurrentUserRef) -> UserRef:
    if user.role != "owner":
        raise OwnerOnly
    return user


CurrentOwner = Annotated[UserRef, Depends(require_owner)]


async def require_can_connect(user: CurrentUserRef) -> UserRef:
    # владельцу право не выдают: оно у него по роли
    if user.role != "owner" and not user.can_connect_accounts:
        raise CannotConnectAccounts
    return user


CanConnectAccounts = Annotated[UserRef, Depends(require_can_connect)]
