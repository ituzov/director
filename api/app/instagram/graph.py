"""Клиент Graph API Instagram: одна функция на один запрос к Meta.

Без базы и бизнес-правил, когда звать решает сервис. httpx.AsyncClient приходит
снаружи: один на всю операцию, а в тестах с подменённой сетью.
Токены ходят в адресе (так требует Meta), поэтому логгер httpx приглушён.
"""

from dataclasses import dataclass
from typing import Any

import httpx

OAUTH = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
# версия API: та же, что выбрана у вебхуков в кабинете Meta
VERSION = "v26.0"


class GraphError(Exception):
    """Meta ответила ошибкой. Текст ошибки не храним: Meta кладёт в него куски запроса."""

    def __init__(self, status: int, code: object = None, type_: object = None) -> None:
        super().__init__(f"Graph API ответил {status} (code={code}, type={type_})")
        self.status = status
        self.code = code
        self.type = type_


@dataclass(frozen=True, slots=True)
class ShortToken:
    access_token: str
    user_id: str
    permissions: list[str]


@dataclass(frozen=True, slots=True)
class LongToken:
    access_token: str
    # секунды, около 60 дней
    expires_in: int


@dataclass(frozen=True, slots=True)
class Me:
    # он же entry[].id в вебхуках: проверить на первом живом подключении
    user_id: str
    username: str


async def exchange_code(
    http: httpx.AsyncClient, *, app_id: str, app_secret: str, redirect_uri: str, code: str
) -> ShortToken:
    """Код из возврата OAuth в короткий токен на час."""
    data = _json(
        await http.post(
            OAUTH,
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
    )
    # ответ завёрнут в data[], как в документации; старый формат без обёртки тоже примем
    token = data["data"][0] if isinstance(data.get("data"), list) else data
    permissions = token.get("permissions") or ""
    return ShortToken(
        access_token=token["access_token"],
        user_id=str(token["user_id"]),
        permissions=permissions.split(",") if isinstance(permissions, str) else permissions,
    )


async def long_lived_token(
    http: httpx.AsyncClient, *, app_secret: str, short_token: str
) -> LongToken:
    """Короткий токен в долгий на 60 дней. Только на сервере: нужен секрет."""
    data = _json(
        await http.get(
            f"{GRAPH}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret,
                "access_token": short_token,
            },
        )
    )
    return LongToken(access_token=data["access_token"], expires_in=int(data["expires_in"]))


async def refresh_token(http: httpx.AsyncClient, *, token: str) -> LongToken:
    """Долгий токен в новый долгий на 60 дней. Meta требует: старше суток и не истёк."""
    data = _json(
        await http.get(
            f"{GRAPH}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
        )
    )
    return LongToken(access_token=data["access_token"], expires_in=int(data["expires_in"]))


async def get_me(http: httpx.AsyncClient, *, token: str) -> Me:
    data = _json(
        await http.get(
            f"{GRAPH}/{VERSION}/me",
            params={"fields": "user_id,username", "access_token": token},
        )
    )
    return Me(user_id=str(data["user_id"]), username=data["username"])


async def subscribe(http: httpx.AsyncClient, *, token: str, fields: list[str]) -> None:
    """Подписать аккаунт на поля вебхука: без этого Meta шлёт только тестовые события."""
    data = _json(
        await http.post(
            f"{GRAPH}/{VERSION}/me/subscribed_apps",
            params={"subscribed_fields": ",".join(fields), "access_token": token},
        )
    )
    if data.get("success") is not True:
        raise GraphError(200, type_="subscribe_not_confirmed")


async def send_message(
    http: httpx.AsyncClient,
    *,
    token: str,
    ig_user_id: str,
    recipient: dict[str, str],
    text: str,
    button: dict[str, str] | None = None,
) -> None:
    """Сообщение в директ. recipient {"comment_id"} это Private Reply на коммент,
    {"id"} обычное сообщение человеку. С кнопкой уходит шаблоном button."""
    if button:
        message: dict[str, Any] = {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": text,
                    "buttons": [{"type": "postback", **button}],
                },
            }
        }
    else:
        message = {"text": text}
    _json(
        await http.post(
            f"{GRAPH}/{VERSION}/{ig_user_id}/messages",
            params={"access_token": token},
            json={"recipient": recipient, "message": message},
        )
    )


async def follows_business(http: httpx.AsyncClient, *, token: str, person_id: str) -> bool:
    """Подписан ли человек на аккаунт токена. Meta отдаёт только с согласия человека:
    он писал в директ или нажимал кнопку."""
    data = _json(
        await http.get(
            f"{GRAPH}/{VERSION}/{person_id}",
            params={"fields": "is_user_follow_business", "access_token": token},
        )
    )
    return data.get("is_user_follow_business") is True


async def reply_to_comment(
    http: httpx.AsyncClient, *, token: str, comment_id: str, text: str
) -> None:
    """Публичный ответ под комментом."""
    _json(
        await http.post(
            f"{GRAPH}/{VERSION}/{comment_id}/replies",
            params={"access_token": token},
            json={"message": text},
        )
    )


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise GraphError(response.status_code, type_="not_json")
    if response.is_error:
        # Graph API: {"error": {"type", "code"}}; обмен кода: {"error_type", "code"}
        error = data.get("error") if isinstance(data.get("error"), dict) else data
        raise GraphError(
            response.status_code,
            code=error.get("code"),
            type_=error.get("type") or error.get("error_type"),
        )
    return data
