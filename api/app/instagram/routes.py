"""HTTP-ручки instagram. Тонкие: разобрать запрос, позвать сервис, собрать ответ."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import StringConstraints

from app import identity
from app.db import SessionDep
from app.instagram import service
from app.instagram.exceptions import (
    AccountNotFound,
    AccountUnavailable,
    AppSecretRequired,
    InstagramError,
    InvalidOAuthState,
    MetaAppRequired,
    MetaUnavailable,
    OAuthFailed,
    PublicUrlRequired,
)
from app.instagram.models import Account, MetaApp
from app.instagram.schemas import (
    AccountOut,
    InboxCountsOut,
    InboxItemOut,
    InboxPageOut,
    MediaOut,
    MediaPageOut,
    MetaAppIn,
    MetaAppOut,
    OAuthCallbackIn,
    OAuthUrlOut,
    SelectedMediaOut,
    WebhookCheckOut,
)

router = APIRouter(prefix="/instagram", tags=["instagram"])
# адрес вебхука постоянный и без префикса модуля: его владелец вписал в кабинет Meta
webhook_router = APIRouter(tags=["instagram"])

_STATUS = {
    AppSecretRequired: status.HTTP_422_UNPROCESSABLE_CONTENT,
    MetaAppRequired: status.HTTP_409_CONFLICT,
    PublicUrlRequired: status.HTTP_409_CONFLICT,
    InvalidOAuthState: status.HTTP_400_BAD_REQUEST,
    OAuthFailed: status.HTTP_502_BAD_GATEWAY,
    AccountNotFound: status.HTTP_404_NOT_FOUND,
    AccountUnavailable: status.HTTP_409_CONFLICT,
    MetaUnavailable: status.HTTP_502_BAD_GATEWAY,
}


async def instagram_error_handler(request: Request, exc: InstagramError) -> JSONResponse:
    # detail это имя ошибки: по нему Next выбирает текст для человека
    return JSONResponse({"detail": type(exc).__name__}, status_code=_STATUS[type(exc)])


def _meta_app_out(meta_app: MetaApp) -> MetaAppOut:
    return MetaAppOut(
        app_id=meta_app.app_id,
        verify_token=meta_app.verify_token,
        updated_at=meta_app.updated_at,
        webhook_verified_at=meta_app.webhook_verified_at,
        webhook_url=service.public_url(service.WEBHOOK_PATH),
        redirect_uri=service.public_url(service.OAUTH_CALLBACK_PATH),
        privacy_url=service.public_url(service.PRIVACY_PATH),
    )


@router.get("/app")
async def get_meta_app(session: SessionDep, owner: identity.CurrentOwner) -> MetaAppOut | None:
    # None, пока ключи не вводили: админка покажет пустую форму
    meta_app = await service.get_meta_app(session)
    return _meta_app_out(meta_app) if meta_app else None


@router.put("/app")
async def put_meta_app(
    body: MetaAppIn, session: SessionDep, owner: identity.CurrentOwner
) -> MetaAppOut:
    meta_app = await service.save_meta_app(session, app_id=body.app_id, app_secret=body.app_secret)
    return _meta_app_out(meta_app)


@router.post("/app/webhook-check")
async def check_webhook(session: SessionDep, owner: identity.CurrentOwner) -> WebhookCheckOut:
    error = await service.check_webhook(session)
    return WebhookCheckOut(ok=error is None, error=error)


def _account_out(account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        ig_user_id=account.ig_user_id,
        username=account.username,
        status=account.status,
        connected_at=account.connected_at,
    )


@router.get("/accounts")
async def list_accounts(session: SessionDep, user: identity.CurrentUserRef) -> list[AccountOut]:
    # аккаунты установки видит любой вошедший: роли на аккаунт появятся позже
    return [_account_out(account) for account in await service.list_accounts(session)]


@router.get("/oauth/url")
async def get_oauth_url(session: SessionDep, user: identity.CanConnectAccounts) -> OAuthUrlOut:
    return OAuthUrlOut(url=await service.oauth_url(session, user_id=user.id))


@router.post("/oauth/callback")
async def oauth_callback(
    body: OAuthCallbackIn, session: SessionDep, user: identity.CanConnectAccounts
) -> AccountOut:
    account = await service.connect_account(
        session, user_id=user.id, code=body.code, state=body.state
    )
    return _account_out(account)


@webhook_router.get(service.WEBHOOK_PATH, response_class=PlainTextResponse)
async def verify_webhook(
    session: SessionDep,
    # Meta отдаёт число; эхо произвольной строки из запроса это заготовка для атаки
    challenge: Annotated[str, Query(alias="hub.challenge", pattern=r"^[0-9]{1,32}$")],
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
) -> str:
    if not await service.verify_webhook(session, mode=mode, token=token):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return challenge


@webhook_router.post(service.WEBHOOK_PATH)
async def receive_webhook(request: Request, session: SessionDep) -> Response:
    # тело читаем сырым: подпись считается от байтов, а не от разобранного JSON
    accepted = await service.receive_webhook(
        session, body=await request.body(), signature=request.headers.get("x-hub-signature-256")
    )
    return Response(status_code=status.HTTP_200_OK if accepted else status.HTTP_403_FORBIDDEN)


@router.get("/accounts/{account_id}/media")
async def list_media(
    account_id: uuid.UUID,
    session: SessionDep,
    user: identity.CurrentUserRef,
    after: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 24,
) -> MediaPageOut:
    """Посты аккаунта для выбора в автоответе. Закладка after из прошлого ответа."""
    page = await service.list_media(session, account_id, after=after, limit=limit)
    return MediaPageOut(items=[_media_out(m) for m in page.items], next=page.after)


@router.get("/accounts/{account_id}/inbox/counts")
async def inbox_counts(
    account_id: uuid.UUID, session: SessionDep, user: identity.CurrentUserRef
) -> InboxCountsOut:
    """Сколько событий ленты с каждым итогом: для вкладок «Всех событий»."""
    return InboxCountsOut(counts=await service.inbox_counts(session, account_id))


@router.get("/accounts/{account_id}/inbox")
async def list_inbox(
    account_id: uuid.UUID,
    session: SessionDep,
    user: identity.CurrentUserRef,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    # фильтр: вид события и итог разбора
    kind: Literal["comment", "postback", "message"] | None = None,
    result: Literal["taken", "nobody", "skipped", "failed"] | None = None,
) -> InboxPageOut:
    """Лента входящих аккаунта: что пришло от Meta и кто это взял. Свежие сверху,
    закладка before из прошлого ответа."""
    page = await service.list_inbox(
        session, account_id, before=before, limit=limit, kind=kind, result=result
    )
    return InboxPageOut(
        items=[InboxItemOut.model_validate(i, from_attributes=True) for i in page.items],
        next=page.next,
    )


# id поста встаёт в путь запроса к Meta: только цифры, иначе «me/..» ушёл бы куда угодно
MediaIdQuery = Annotated[str, StringConstraints(pattern=r"^\d{1,30}$")]


@router.get("/accounts/{account_id}/media/selected")
async def get_selected_media(
    account_id: uuid.UUID,
    session: SessionDep,
    user: identity.CurrentUserRef,
    ids: Annotated[list[MediaIdQuery], Query(max_length=50)],
) -> SelectedMediaOut:
    """Выбранные посты автоответа по id: миниатюры для формы. Удалённые в missing."""
    found = await service.get_media(session, account_id, list(dict.fromkeys(ids)))
    return SelectedMediaOut(
        items=[_media_out(m) for m in found.values() if m is not None],
        missing=[i for i, m in found.items() if m is None],
    )


def _media_out(media: dict) -> MediaOut:
    return MediaOut(
        id=str(media.get("id")),
        caption=media.get("caption"),
        type=media.get("media_product_type"),
        media_type=media.get("media_type"),
        thumbnail=media.get("thumbnail_url") or media.get("media_url"),
        permalink=media.get("permalink"),
        timestamp=media.get("timestamp"),
        comments_count=media.get("comments_count"),
    )
