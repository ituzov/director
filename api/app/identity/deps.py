"""Зависимости identity для ручек: кто делает запрос."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import SessionDep
from app.identity import service
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
