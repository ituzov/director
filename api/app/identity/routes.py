"""HTTP-ручки identity. Тонкие: разобрать запрос, позвать сервис, собрать ответ."""

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.db import SessionDep
from app.identity import service
from app.identity.deps import BearerToken, CurrentUser
from app.identity.exceptions import (
    CannotConnectAccounts,
    IdentityError,
    InvalidCredentials,
    InvalidSetupToken,
    OwnerAlreadyExists,
    OwnerOnly,
    SetupDisabled,
    WeakPassword,
)
from app.identity.schemas import LoginIn, SetupIn, SetupStatusOut, TokenOut, UserOut

router = APIRouter(tags=["identity"])

_STATUS = {
    SetupDisabled: status.HTTP_404_NOT_FOUND,  # снаружи setup будто и нет
    InvalidSetupToken: status.HTTP_403_FORBIDDEN,
    OwnerAlreadyExists: status.HTTP_409_CONFLICT,
    WeakPassword: status.HTTP_422_UNPROCESSABLE_CONTENT,
    InvalidCredentials: status.HTTP_401_UNAUTHORIZED,
    OwnerOnly: status.HTTP_403_FORBIDDEN,
    CannotConnectAccounts: status.HTTP_403_FORBIDDEN,
}


async def identity_error_handler(request: Request, exc: IdentityError) -> JSONResponse:
    # detail это имя ошибки: по нему Next выбирает текст для человека
    return JSONResponse({"detail": type(exc).__name__}, status_code=_STATUS[type(exc)])


@router.get("/setup")
async def setup_status(session: SessionDep) -> SetupStatusOut:
    # публичная: по ней Next решает, показать вход или первую регистрацию
    return SetupStatusOut(needed=await service.setup_needed(session))


@router.post("/setup", status_code=status.HTTP_201_CREATED)
async def setup(body: SetupIn, session: SessionDep) -> TokenOut:
    await service.register_owner(
        session, token=body.token, email=body.email, password=body.password
    )
    # владелец создан, сразу входим: второй раз вводить пароль незачем
    token = await service.login(session, email=body.email, password=body.password)
    return TokenOut(token=token)


@router.post("/auth/login")
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    token = await service.login(session, email=body.email, password=body.password)
    return TokenOut(token=token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(credentials: BearerToken, session: SessionDep) -> None:
    await service.logout(session, credentials.credentials)


@router.get("/auth/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
