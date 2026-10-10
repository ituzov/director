"""Схемы HTTP: что ручки instagram принимают и отдают. Модели наружу не отдаём."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

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

    model_config = ConfigDict(from_attributes=True)

    app_id: str
    verify_token: str
    updated_at: datetime
