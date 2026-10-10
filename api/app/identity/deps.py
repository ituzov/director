"""Зависимости identity для ручек: кто делает запрос."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import SessionDep
from app.identity import service
from app.identity.contracts import UserRef
from app.identity.exceptions import OwnerOnly
from app.identity.models import User

# Нет заголовка Authorization: Bearer ... HTTPBearer сам ответит 401
_bearer = HTTPBearer()

BearerToken = Annotated[HTTPAuthorizationCredentials, Depends(_bearer)]


async def get_current_user(session: SessionDep, credentials: BearerToken) -> User:
    user = await service.user_by_token(session, credentials.credentials)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Сессия недействительна",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
