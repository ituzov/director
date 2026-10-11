"""Схемы HTTP: что ручки instagram принимают и отдают. Модели наружу не отдаём."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

# Формат строгий: вставленное не то (например, токен IGAA... вместо секрета)
# ловим сразу, а не когда не сойдётся подпись вебхука
AppId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{1,32}$")]
# pattern проверяется до to_lower, поэтому в нём оба регистра
AppSecret = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[0-9a-fA-F]{32}$")
]


class MetaAppIn(BaseModel):
    app_id: AppId
    # None: секрет уже задан и не меняется
    app_secret: AppSecret | None = None


class MetaAppOut(BaseModel):
    """Секрета здесь нет и не будет: наружу он не уходит даже зашифрованным."""

    app_id: str
    verify_token: str
    updated_at: datetime
    # Meta подтвердила адрес вебхука; None, пока владелец не нажал «Подтвердить» в кабинете
    webhook_verified_at: datetime | None
    # строки для кабинета Meta. None, пока не задан адрес сервера
    webhook_url: str | None
    redirect_uri: str | None
    privacy_url: str | None
